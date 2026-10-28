from datetime import datetime as timezone


class h_Clock:
    def utcnow(self):
        return 0

    def utcfromtimestamp(self, t):
        return t


h_v0 = timezone.utcnow()  # S


def h_run():
    return None
