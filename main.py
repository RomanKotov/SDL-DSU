from server import Server
from gui import App


def main():
    server = Server()
    server.start_background()
    app = App(server)
    app.run()


if __name__ == "__main__":
    main()
