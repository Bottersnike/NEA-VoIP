import sys

if __name__ == '__main__':
    if 'server' in sys.argv:
        from .server import Server

        Server().mainloop()
    else:
        from .client import Client

        Client().mainloop()
