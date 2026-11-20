import struct
from uuid import UUID


EFFECT_BUFFER = 0x5BDF54
RESUME_AUDIO_PATH = 0x4436BF
WAVES_REVERB = UUID('87fc0268-9a55-4360-95aa-004a1d9de26c')
WAVES_INTERFACE = UUID('46858c3a-0dc6-45e3-b760-d4eef16cb325')

# Decay seconds, high-frequency decay ratio and late reverb level in
# millibels, in the Windows SDK's DSFX_I3DL2_ENVIRONMENT_PRESET order.
I3DL2_PRESETS = (
    (1.49, .83, 200),    # Default
    (1.49, .83, 200),    # Generic
    (.17, .10, 207),     # Padded cell
    (.40, .83, 53),      # Room
    (1.49, .54, 1030),   # Bathroom
    (.50, .10, -1104),   # Living room
    (2.31, .64, 83),     # Stone room
    (4.32, .59, -289),   # Auditorium
    (3.92, .70, -2),     # Concert hall
    (2.91, 1.30, -302),  # Cave
    (7.24, .33, 16),     # Arena
    (10.05, .23, 198),   # Hangar
    (.30, .10, -1630),   # Carpeted hallway
    (1.49, .59, 441),    # Hallway
    (2.70, .79, 395),    # Stone corridor
    (1.49, .86, -4),     # Alley
    (1.49, .54, -613),   # Forest
    (1.49, .67, -2217),  # City
    (1.49, .21, -2014),  # Mountains
    (1.49, .83, 500),    # Quarry
    (1.49, .50, -2514),  # Plain
    (1.65, 1.50, -1153), # Parking lot
    (2.81, .14, 648),    # Sewer pipe
    (1.49, .10, 1700),   # Underwater
    (1.10, .83, 500),    # Small room
    (1.30, .83, -200),   # Medium room
    (1.50, .83, -1000),  # Large room
    (1.80, .70, -800),   # Medium hall
    (1.80, .70, -1400),  # Large hall
    (1.30, .90, 0),      # Plate
)


def reverb_data(add):
    desc = add(struct.pack('<II16sII', 32, 0, WAVES_REVERB.bytes_le, 0, 0), 4)
    iid = add(WAVES_INTERFACE.bytes_le, 4)
    # Match the late reverb gain and decay within the Waves DMO's limits.
    presets = add(b''.join(
        struct.pack('<4f', 0, min(0, (level - 1000) / 100), min(seconds * 1000, 3000), min(ratio, .999))
        for seconds, ratio, level in I3DL2_PRESETS
    ), 4)
    return desc, iid, presets


def emit_reverb_fallback(code, desc, iid, presets):
    entry = code.label('reverb_fallback')
    code.emit('5f 85 c0')  # Finish the displaced SetFX result check.
    code.to_address('0f 84', 0x443671)
    code.emit('3d 54 01 04 80')  # REGDB_E_CLASSNOTREG
    code.to_address('0f 85', 0x44365C)

    # The game's audio path is paused here. Attach the Waves reverb before resuming it.
    code.emit('a1', EFFECT_BUFFER)
    code.emit('6a 00 68', desc)
    code.emit('6a 01 8b 10 50 ff 52 54 85 c0')  # SetFX(1, &desc, NULL)
    code.relative('75', 'clear_reverb')

    code.emit('a1', EFFECT_BUFFER)
    code.emit('8d 4c 24 04 51 68', iid)
    code.emit('6a 00 68', desc + 8)
    code.emit('8b 10 50 ff 52 5c 85 c0')  # GetObjectInPath(..., &localEffect)
    code.relative('78', 'clear_reverb')

    code.emit('31 c0 83 fb 1e')  # Default preset if the game passes an out-of-range index.
    code.relative('77', 'waves_parameters')
    code.emit('8b 44 9c 08')  # Map the scene number using the original on-stack preset array.
    code.label('waves_parameters')
    code.emit('c1 e0 04 05', presets)
    code.emit('8b 4c 24 04 8b 11 50 51 ff 52 0c')  # SetAllParameters
    code.emit('50 8b 4c 24 08 8b 11 51 ff 52 08 58 85 c0')  # Release; restore HRESULT.
    code.to_address('0f 89', RESUME_AUDIO_PATH)

    # An unavailable effect must not leave this DirectMusic path paused.
    code.label('clear_reverb')
    code.emit('a1', EFFECT_BUFFER)
    code.emit('8b 10 6a 00 6a 00 6a 00 50 ff 52 54')  # SetFX(0, NULL, NULL)
    code.to_address('e9', RESUME_AUDIO_PATH)
    return entry
