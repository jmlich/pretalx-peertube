from django.apps import AppConfig
from django.utils.translation import gettext_lazy

from . import __version__


class PluginApp(AppConfig):
    name = "pretalx_peertube"
    verbose_name = "Peertube integration"

    class PretalxPluginMeta:
        name = gettext_lazy("Peertube integration")
        author = "Tobias Kunze, Jozef Mlich"
        description = gettext_lazy(
            "Show Peertube videos embedded on talk pages. Set URLs manually or via API."
        )
        visible = True
        version = __version__
        category = "RECORDING"
        settings_links = [
            (gettext_lazy("Settings"), "plugins:pretalx_peertube:settings", {})
        ]

    def ready(self):
        from . import signals  # noqa: F401, PLC0415
