from pkg import compat


class h_Clock:
    def utcnow(self):
        return 0

    def utcfromtimestamp(self, t):
        return t


h_v0 = compat.datetime.utcnow()  # S


def h_run():
    return None
