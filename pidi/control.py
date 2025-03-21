from gpiozero import Button
import atexit
import time
import os
from enum import IntEnum


class Action(IntEnum):
    PLAY = 5
    STOP = 16
    PREV = 6
    NEXT = 20


class Control():

    # "handle_press" will be called every time a button is pressed
    # It receives one argument: the associated input pin.
    def handle_press(self, action):
        print(action)
        try:
            self._client.control(action)
        except Exception as e:
            print(f"Unhandled exception: {e}")

    def __init__(self, client):
        self._button_map = [
            (Action.PLAY, "playPause"),
            (Action.STOP, "stop"),
            (Action.PREV, "previous"),
            (Action.NEXT, "next")]
        self._buttons = {}
        self._client = client


        # Buttons connect to ground when pressed, so we should set them up
        # with a "PULL UP", which weakly pulls the input signal to 3.3V.

        # Loop through out buttons and attach the "handle_button" function to each
        # We're watching the "FALLING" edge (transition from 3.3V to Ground) and
        # picking a generous bouncetime of 100ms to smooth out button presses.
        for pin, action in self._button_map:
            print(f"Registering pin {pin}, {action}")
            self._buttons[pin] = Button(pin)
            self._buttons[pin].when_pressed = lambda action=action: self.handle_press(action)
        print(self._buttons)
