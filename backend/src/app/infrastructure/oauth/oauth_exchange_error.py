class OAuthExchangeError(Exception):
    def __init__(self, *, cancelled: bool = False) -> None:
        super().__init__("access_denied" if cancelled else "OAuth exchange failed")
        self.cancelled = cancelled
