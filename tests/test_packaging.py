from importlib.metadata import distribution


def test_distribution_and_cli_entrypoint_use_canonical_name():
    package = distribution("jenkins-cli-mcp")
    assert package.metadata["Name"] == "jenkins-cli-mcp"
    assert any(
        entry_point.name == "jenkins-mcp"
        and entry_point.value == "jenkins_mcp.cli:main"
        for entry_point in package.entry_points
    )
