from vibedom.words import generate_session_id

def test_generate_session_id_format():
    sid = generate_session_id('myapp')
    parts = sid.split('-')
    assert parts[0] == 'myapp'
    assert len(parts) == 3  # workspace, adjective, noun

def test_generate_session_id_workspace_with_hyphens():
    sid = generate_session_id('rabbitmq-talk')
    assert sid.startswith('rabbitmq-talk-')
    assert len(sid.split('-')) == 4  # two workspace parts + adjective + noun

def test_generate_session_id_is_random():
    ids = {generate_session_id('myapp') for _ in range(20)}
    assert len(ids) > 1  # should not always produce the same ID
