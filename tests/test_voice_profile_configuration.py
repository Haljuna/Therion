from therion.config.local import _validate_config


def test_approved_profile_remains_enabled_and_preserves_other_settings():
    result = _validate_config({'tts': {'enabled': True, 'provider': 'kokoro', 'voice': 'alex_santa_c',
                                      'model_root': 'models', 'python_path': 'python', 'warm_on_start': True}})
    assert result['tts']['enabled'] is True
    assert result['tts']['voice'] == 'alex_santa_c'
    assert result['tts']['warm_on_start'] is True


def test_unknown_profile_cannot_become_enabled():
    result = _validate_config({'tts': {'enabled': True, 'voice': 'unapproved'}})
    assert result['tts']['enabled'] is False
