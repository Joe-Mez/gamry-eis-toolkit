"""Errors that are the user's to fix (bad config, bad file). Shown without a traceback."""


class UserError(Exception):
    """A problem with the input or the configuration, explained in plain words."""
