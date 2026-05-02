from project_agent.core.interfaces import Plugin


class ExamplePlugin:
    name = "example"

    def setup(self) -> None:
        return None


plugin: Plugin = ExamplePlugin()
