import pytest
from pathlib import Path
from vibedom.project_config import ProjectConfig, Mount


def test_project_config_loads_base_image(tmp_path):
    """Should parse base_image from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text('base_image: wapi-php-fpm:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.base_image == 'wapi-php-fpm:latest'


def test_project_config_loads_network(tmp_path):
    """Should parse network from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text(
        'base_image: wapi-php-fpm:latest\nnetwork: wapi_shared\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.network == 'wapi_shared'


def test_project_config_returns_none_if_no_file(tmp_path):
    """Should return None when no vibedom.yml present."""
    config = ProjectConfig.load(tmp_path)
    assert config is None


def test_project_config_optional_fields(tmp_path):
    """network is optional."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.network is None


def test_project_config_rejects_unknown_fields(tmp_path):
    """Should raise ValueError for unrecognised fields."""
    (tmp_path / 'vibedom.yml').write_text('typo_field: oops\n')
    with pytest.raises(ValueError, match='Unknown'):
        ProjectConfig.load(tmp_path)


def test_project_config_loads_host_aliases(tmp_path):
    """Should parse host_aliases mapping from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text(
        'host_aliases:\n  wapi-redis: host\n  wapi-mysql: host\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.host_aliases == {'wapi-redis': 'host', 'wapi-mysql': 'host'}


def test_project_config_host_aliases_defaults_to_none(tmp_path):
    """host_aliases is optional and defaults to None."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.host_aliases is None


def test_project_config_host_aliases_with_explicit_ip(tmp_path):
    """host_aliases should support explicit IP addresses."""
    (tmp_path / 'vibedom.yml').write_text(
        'host_aliases:\n  custom-service: 192.168.1.100\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.host_aliases == {'custom-service': '192.168.1.100'}


def test_project_config_loads_setup(tmp_path):
    """Should parse setup list from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text(
        'setup:\n  - composer install\n  - cp .env.example .env\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.setup == ['composer install', 'cp .env.example .env']


def test_project_config_setup_defaults_to_none(tmp_path):
    """setup is optional and defaults to None."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.setup is None


def test_project_config_loads_sync_exclude(tmp_path):
    """Should parse sync_exclude list from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text(
        'sync_exclude:\n  - vendor/\n  - storage/logs/\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.sync_exclude == ['vendor/', 'storage/logs/']


def test_project_config_sync_exclude_defaults_to_none(tmp_path):
    """sync_exclude is optional and defaults to None."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.sync_exclude is None


def test_project_config_loads_env(tmp_path):
    """Should parse env mapping from vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text(
        'env:\n  DB_PORT: 1234\n  DB_HOST: host.docker.internal\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.env == {'DB_PORT': 1234, 'DB_HOST': 'host.docker.internal'}


def test_project_config_env_defaults_to_none(tmp_path):
    """env is optional and defaults to None."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.env is None


def test_mounts_defaults_to_none(tmp_path):
    """mounts is optional and defaults to None."""
    (tmp_path / 'vibedom.yml').write_text('base_image: myimage:latest\n')
    config = ProjectConfig.load(tmp_path)
    assert config.mounts is None


def test_mounts_scalar_entry_is_rw(tmp_path):
    """A scalar entry mounts read-write; name is the basename."""
    target = tmp_path / 'www'
    target.mkdir()
    (tmp_path / 'vibedom.yml').write_text(f'mounts:\n  - {target}\n')
    config = ProjectConfig.load(tmp_path)
    assert config.mounts == [Mount(host_path=target.resolve(), name='www', read_only=False)]


def test_mounts_dot_resolves_to_config_dir(tmp_path):
    """'.' resolves to the directory containing vibedom.yml."""
    (tmp_path / 'vibedom.yml').write_text('mounts:\n  - .\n')
    config = ProjectConfig.load(tmp_path)
    assert config.mounts == [Mount(host_path=tmp_path.resolve(), name=tmp_path.name, read_only=False)]


def test_mounts_mapping_with_alias_and_ro(tmp_path):
    """Mapping form supports 'as' and 'ro'."""
    target = tmp_path / 'shared-libs'
    target.mkdir()
    (tmp_path / 'vibedom.yml').write_text(
        f'mounts:\n  - path: {target}\n    as: shared\n    ro: true\n'
    )
    config = ProjectConfig.load(tmp_path)
    assert config.mounts == [Mount(host_path=target.resolve(), name='shared', read_only=True)]


def test_mounts_duplicate_name_raises(tmp_path):
    """Two entries resolving to the same name is a config error."""
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    (tmp_path / 'vibedom.yml').write_text(
        f'mounts:\n  - path: {tmp_path / "a"}\n    as: dup\n'
        f'  - path: {tmp_path / "b"}\n    as: dup\n'
    )
    with pytest.raises(ValueError, match='Duplicate mount name'):
        ProjectConfig.load(tmp_path)


def test_mounts_mapping_missing_path_raises(tmp_path):
    """A mapping entry without 'path' is a config error."""
    (tmp_path / 'vibedom.yml').write_text('mounts:\n  - as: oops\n')
    with pytest.raises(ValueError, match="missing 'path'"):
        ProjectConfig.load(tmp_path)
