import random

ADJECTIVES = [
    'bold', 'brave', 'bright', 'calm', 'clear', 'clever', 'eager',
    'fierce', 'gentle', 'happy', 'jolly', 'keen', 'kind', 'lively',
    'merry', 'noble', 'proud', 'quick', 'quiet', 'rapid', 'sharp',
    'sleek', 'smart', 'steady', 'swift', 'warm', 'wise', 'witty',
    'agile', 'amber', 'ancient', 'benign', 'candid', 'cosmic', 'deft',
    'early', 'earnest', 'fair', 'famous', 'fluid', 'fresh', 'grand',
    'great', 'hardy', 'honest', 'humble', 'ideal', 'known', 'large',
    'light', 'liquid', 'lucky', 'major', 'mental', 'micro', 'modern',
    'moral', 'nimble', 'novel', 'noted', 'open', 'patient', 'plain',
]

NOUNS = [
    'babbage', 'boole', 'curie', 'darwin', 'dijkstra', 'einstein',
    'euler', 'faraday', 'fermat', 'feynman', 'fibonacci', 'franklin',
    'gauss', 'goedel', 'hamilton', 'hawking', 'hilbert', 'hopper',
    'huffman', 'turing', 'knuth', 'laplace', 'leibniz', 'lovelace',
    'maxwell', 'mendel', 'newton', 'noether', 'pascal', 'planck',
    'poincare', 'ramanujan', 'shannon', 'shor', 'tesla', 'thompson',
    'torvalds', 'von-neumann', 'wiles', 'wozniak', 'ritchie', 'liskov',
    'mccarthy', 'minsky', 'naur', 'perlis', 'hamming', 'codd', 'chen',
    'backus', 'allen', 'adleman', 'rivest', 'shamir', 'diffie', 'hellman',
    'lamport', 'gray', 'brooks', 'floyd', 'hoare', 'wirth', 'stroustrup',
]


def generate_session_id(workspace_name: str) -> str:
    """Generate a human-readable session ID.

    Args:
        workspace_name: Name of the workspace directory

    Returns:
        ID in format '<workspace>-<adjective>-<noun>'

    Example:
        >>> generate_session_id('myapp')
        'myapp-happy-turing'
    """
    adjective = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    return f'{workspace_name}-{adjective}-{noun}'
