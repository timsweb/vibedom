import pytest
from pathlib import Path
from vibedom.project_config import ProjectConfig


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
