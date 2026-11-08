# Smart Cane

A smart-cane assistive device project: sensors on the cane, firmware to read them, and a companion app.

## Repository layout

- `firmware/` - on-device firmware for the cane's microcontroller
- `app/` - companion app
- `hardware/` - parts list, pinout, and CAD files
- `interface/` - data format and sample readings shared between firmware and app
- `docs/` - setup, tests, and demo notes

## Status

Early skeleton. Hardware parts, microcontroller, and software stack are not yet decided; each directory has a NOTES file listing what needs to be filled in.

## Functionality

Safety. Button pressed 30 sec of alert activation, cancel alert.
Walking? Track if acceleration suddenly stops between increments.
Serious vs non-serious falls. If cane experiences sudden random acceleration changes.

Doctor reports. Send important information. E.g. falls. Patient (caretaker) can remove falls off the system.
