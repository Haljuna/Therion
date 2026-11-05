from therion.voice.preparation import VoicePreparation


def test_individual_deadlines_measurements_and_cancelled_completions():
    now = [10.0]
    status = VoicePreparation(clock=lambda: now[0])
    status.begin({'ai': 'preparing', 'speech': 'preparing', 'transcription': 'ready'},
                 {'ai': 90, 'speech': 120, 'transcription': 120})
    now[0] = 15.0
    status.finish('speech')
    assert status.snapshot()['speech'] == {'state': 'ready', 'seconds': 5.0}
    assert not status.ready
    now[0] = 100.0
    assert status.expired() == 'ai'
    status.stop()
    status.finish('ai')
    assert status.snapshot()['ai']['state'] == 'timeout'
    assert not status.ready
    status.begin({'ai': 'preparing'}, {'ai': 90})
    status.stop()
    status.finish('ai')
    assert status.snapshot()['ai']['state'] == 'stopped'


def test_success_and_retry_do_not_carry_over_failed_state():
    status = VoicePreparation()
    status.begin({'speech': 'preparing'}, {'speech': 120})
    status.finish('speech', 'failed')
    assert not status.ready
    status.begin({'speech': 'preparing'}, {'speech': 120})
    status.finish('speech')
    assert status.ready
