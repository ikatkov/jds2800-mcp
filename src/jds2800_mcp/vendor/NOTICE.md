The unmodified `legacy.py` contains Kristoff Bonne's
[jds6600_python](https://github.com/on1arf/jds6600_python), version 0.1.0.
It is covered by the accompanying MIT LICENSE.

The adapter bypasses its constructor (which stores the serial connection on
the class), replaces its serial read/write methods with bounded line framing,
and fixes negative phase handling in the public driver. Do not use the legacy
class directly.
