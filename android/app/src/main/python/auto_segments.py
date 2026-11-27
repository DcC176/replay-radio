# Android 精简版 stub：自动分段需要 ffmpeg + 本机音频分析，移动端不启用。
NO_WINDOW = True
HIDE_SI = True

def yield_to_playback(*a, **kw):
    return True
