# app/theme.py

class ThemeManager:
    def __init__(self, logger=None):
        self.logger = logger
        self.themes = {
            "light": {
                "primary": "#1976d2",
                "secondary": "#ffffff",
                "background": "linear-gradient(135deg, #e0e0e0, #ffffff)",
                "chat-bg": "#f9f9f9",
                "bot-color": "#333399",
                "user-bg": "#007acc",
                "text-color": "#493B3B",
                "input-bg": "#ffffff",
                "border-color": "#ccc",
                "input-focus": "#1976d2"
            },
            "dark": {
                "primary": "#66ff00",
                "secondary": "#ffffff",
                "background": "linear-gradient(135deg, #1e1e1e, #121212)",
                "chat-bg": "#1c1c1c",
                "bot-color": "#ffcc00",
                "user-bg": "#6faa00",
                "text-color": "#ffffff",
                "input-bg": "#2a2a2a",
                "border-color": "#444444",
                "input-focus": "#00ccff"
            }
        }

    def get_theme(self, name: str) -> dict:
        theme = self.themes.get(name.lower(), self.themes["light"])
        if self.logger:
            self.logger.info(f"Theme selected: {name}")
        return theme
