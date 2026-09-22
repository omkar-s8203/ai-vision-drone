import numpy as np

from companion.tracking.appearance import AppearanceMemory, compute_signature, similarity
from companion.tracking.base import TrackedTarget
from companion.vision.detector import BBox, Detection

FRAME_W, FRAME_H = 200, 200


def make_frame(color_bgr: tuple[int, int, int]) -> np.ndarray:
    """A solid-color frame - crops of it always have that one color,
    regardless of bbox position/size, which makes similarity assertions
    unambiguous without needing real photos."""
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    frame[:, :] = color_bgr
    return frame


def make_detection(class_id: int, class_name: str, bbox: BBox) -> Detection:
    return Detection(bbox=bbox, score=0.9, class_id=class_id, class_name=class_name, frame_ts=0.0)


def make_target(class_id: int, class_name: str, bbox: BBox) -> TrackedTarget:
    return TrackedTarget(
        target_id=1, bbox=bbox, confidence=0.9, class_id=class_id, class_name=class_name, last_seen_ts=0.0
    )


SOME_BBOX = BBox(x=50, y=50, w=60, h=100)


def test_compute_signature_returns_none_without_a_real_frame():
    assert compute_signature(None, SOME_BBOX, class_id=0) is None


def test_compute_signature_returns_none_for_an_off_frame_bbox():
    frame = make_frame((0, 0, 255))
    off_frame_bbox = BBox(x=-500, y=-500, w=10, h=10)
    assert compute_signature(frame, off_frame_bbox, class_id=0) is None


def test_identical_color_crops_are_highly_similar():
    frame = make_frame((0, 0, 255))  # solid red (BGR)
    sig_a = compute_signature(frame, BBox(0, 0, 50, 50), class_id=0)
    sig_b = compute_signature(frame, BBox(100, 100, 50, 50), class_id=0)
    assert sig_a is not None and sig_b is not None
    assert similarity(sig_a, sig_b) > 0.99


def test_distinctly_different_colors_are_not_similar():
    red_frame = make_frame((0, 0, 255))
    blue_frame = make_frame((255, 0, 0))
    sig_red = compute_signature(red_frame, SOME_BBOX, class_id=0)
    sig_blue = compute_signature(blue_frame, SOME_BBOX, class_id=0)
    assert sig_red is not None and sig_blue is not None
    assert similarity(sig_red, sig_blue) < 0.5


def test_memory_has_no_signature_until_learn_is_called():
    memory = AppearanceMemory()
    assert memory.has_signature is False


def test_learn_then_find_match_relocks_the_same_colored_detection():
    memory = AppearanceMemory(min_similarity=0.5)
    frame = make_frame((0, 0, 255))
    target = make_target(class_id=0, class_name="person", bbox=SOME_BBOX)

    memory.learn(frame, target)

    assert memory.has_signature is True
    same_color_detection = make_detection(0, "person", BBox(10, 10, 40, 40))
    match = memory.find_match(frame, [same_color_detection])
    assert match is same_color_detection


def test_find_match_rejects_a_different_class_even_with_matching_color():
    memory = AppearanceMemory(min_similarity=0.5)
    frame = make_frame((0, 0, 255))
    target = make_target(class_id=0, class_name="person", bbox=SOME_BBOX)
    memory.learn(frame, target)

    wrong_class_detection = make_detection(2, "car", BBox(10, 10, 40, 40))
    assert memory.find_match(frame, [wrong_class_detection]) is None


def test_find_match_rejects_a_dissimilar_color_of_the_same_class():
    memory = AppearanceMemory(min_similarity=0.5)
    red_frame = make_frame((0, 0, 255))
    target = make_target(class_id=0, class_name="person", bbox=SOME_BBOX)
    memory.learn(red_frame, target)

    blue_frame = make_frame((255, 0, 0))
    different_looking_detection = make_detection(0, "person", BBox(10, 10, 40, 40))
    assert memory.find_match(blue_frame, [different_looking_detection]) is None


def test_find_match_without_a_learned_signature_returns_none():
    memory = AppearanceMemory()
    frame = make_frame((0, 0, 255))
    detection = make_detection(0, "person", SOME_BBOX)
    assert memory.find_match(frame, [detection]) is None


def test_find_match_without_a_real_frame_returns_none():
    memory = AppearanceMemory()
    memory.learn(make_frame((0, 0, 255)), make_target(0, "person", SOME_BBOX))
    detection = make_detection(0, "person", SOME_BBOX)
    assert memory.find_match(None, [detection]) is None


def test_forget_clears_the_signature():
    memory = AppearanceMemory()
    memory.learn(make_frame((0, 0, 255)), make_target(0, "person", SOME_BBOX))
    assert memory.has_signature is True

    memory.forget()

    assert memory.has_signature is False


def test_find_match_picks_the_best_of_several_candidates():
    memory = AppearanceMemory(min_similarity=0.0)
    red_frame = make_frame((0, 0, 255))
    memory.learn(red_frame, make_target(0, "person", SOME_BBOX))

    # A mixed frame: one half red (matches), one half green (doesn't).
    mixed = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    mixed[:, : FRAME_W // 2] = (0, 255, 0)  # green half
    mixed[:, FRAME_W // 2 :] = (0, 0, 255)  # red half

    green_side = make_detection(0, "person", BBox(10, 10, 30, 30))
    red_side = make_detection(0, "person", BBox(FRAME_W // 2 + 10, 10, 30, 30))

    match = memory.find_match(mixed, [green_side, red_side])
    assert match is red_side


def test_find_match_refuses_to_guess_between_two_equally_good_candidates():
    """A real field-reported bug: two people in similarly-colored clothing
    - once the original target left frame, find_match() used to just pick
    whichever candidate scored (even marginally) higher, silently relocking
    onto the wrong person with nothing in the UI showing anything had gone
    wrong. Two candidates this close together must be treated as genuinely
    ambiguous and rejected, not resolved by a coin-flip-sized score gap."""
    memory = AppearanceMemory(min_similarity=0.5, min_margin=0.08)
    red_frame = make_frame((0, 0, 255))
    memory.learn(red_frame, make_target(0, "person", SOME_BBOX))

    # Two same-class detections, both an equally strong (identical) color
    # match to the remembered signature - a stand-in for two different
    # people who happen to look similar enough to both clear min_similarity.
    candidate_a = make_detection(0, "person", BBox(10, 10, 30, 30))
    candidate_b = make_detection(0, "person", BBox(120, 10, 30, 30))

    assert memory.find_match(red_frame, [candidate_a, candidate_b]) is None


def test_find_match_accepts_a_clear_winner_even_with_a_second_candidate():
    """The margin check must not make reacquisition impossible whenever a
    second same-class detection happens to be in frame - only when they're
    genuinely close, this project's own actual field-tested scenario is
    still expected to work: one real match, one unrelated-colored bystander."""
    memory = AppearanceMemory(min_similarity=0.0, min_margin=0.08)
    red_frame = make_frame((0, 0, 255))
    memory.learn(red_frame, make_target(0, "person", SOME_BBOX))

    mixed = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    mixed[:, : FRAME_W // 2] = (0, 255, 0)  # green half - unrelated bystander
    mixed[:, FRAME_W // 2 :] = (0, 0, 255)  # red half - the real match

    green_side = make_detection(0, "person", BBox(10, 10, 30, 30))
    red_side = make_detection(0, "person", BBox(FRAME_W // 2 + 10, 10, 30, 30))

    assert memory.find_match(mixed, [green_side, red_side]) is red_side
