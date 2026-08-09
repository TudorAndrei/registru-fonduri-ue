import reflex as rx

config = rx.Config(
    app_name="dashboard",
    app_module_import="dashboard.dashboard",
    show_built_with_reflex=False,
    plugins=[
        # Din 0.9 tema se configurează aici, nu în `rx.App(theme=...)`.
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="inherit", accent_color="iris", radius="large"),
        ),
    ],
    # Registrul este o aplicație de căutare, nu un site public de indexat.
    disable_plugins=[rx.plugins.SitemapPlugin],
)
