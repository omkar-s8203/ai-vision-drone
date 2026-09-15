from __future__ import annotations


class ContactSensor:
    def is_contact(self) -> bool:
        raise NotImplementedError


class NullContactSensor(ContactSensor):
    """Default for sim/dev and for any build without a physical contact
    sensor wired up - always reports no contact."""

    def is_contact(self) -> bool:
        return False


class GpioContactSensor(ContactSensor):
    """Bump/whisker switch on a Pi GPIO pin, for the approach-test 'contact
    confirmed' condition (docs plan M9). Guarded import - only usable on a
    real Pi with the switch wired.
    """

    def __init__(self, pin: int) -> None:
        try:
            from gpiozero import Button  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "gpiozero is not available - GpioContactSensor only runs on a Raspberry "
                "Pi. Use NullContactSensor for development/simulation."
            ) from exc
        self._button = Button(pin)

    def is_contact(self) -> bool:
        return bool(self._button.is_pressed)
