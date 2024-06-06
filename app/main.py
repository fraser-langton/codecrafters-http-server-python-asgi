import gzip
import re
import typing as t
from dataclasses import dataclass, field
from pathlib import Path

import click
import uvicorn
import uvicorn._types as ut

HTTPReceiveEvent = t.Union[
    ut.HTTPRequestEvent,
    ut.HTTPDisconnectEvent,
]

LifeSpanReceiveEvent = t.Union[
    ut.LifespanStartupEvent,
    ut.LifespanShutdownEvent,
]

HTTPSendEvent = t.Union[
    ut.HTTPResponseStartEvent,
    ut.HTTPResponseBodyEvent,
    ut.HTTPResponseTrailersEvent,
    ut.HTTPServerPushEvent,
    ut.HTTPDisconnectEvent,
]

LifeSpanSendEvent = t.Union[
    ut.LifespanStartupCompleteEvent,
    ut.LifespanStartupFailedEvent,
    ut.LifespanShutdownCompleteEvent,
    ut.LifespanShutdownFailedEvent,
]


@dataclass(slots=True)
class Response:
    status: int = field(default=200)
    headers: t.Dict[str, str] = field(default_factory=dict)
    body: str = field(default="")


class Request:
    method: str
    path: str
    headers: t.Dict[str, str]
    body: str = ""
    scope: t.Dict[str, t.Any]

    def __init__(self, scope: ut.HTTPScope, body: bytes | None = None):
        self.method = scope["method"]
        self.path = scope["path"]
        self.headers = {k.decode().lower(): v.decode().lower() for k, v in scope["headers"]}
        self.scope = scope
        if body is not None:
            self.body = body.decode()


async def send_response(
    scope: ut.HTTPScope,
    request: Request,
    response: Response,
    send: t.Callable[[HTTPSendEvent], t.Awaitable[None]],
) -> None:
    body = response.body.encode()
    encoded_headers: t.List[t.Tuple[bytes, bytes]] = [
        (
            k.lower().encode(),
            v.lower().encode(),
        )
        for k, v in response.headers.items()
    ]
    encoded_headers.append((b"content-length", str(len(body)).encode()))

    encoding: t.Optional[str] = None
    client_encodings: t.Set[str] = set(request.headers.get("accept-encoding", "").split(", "))
    allowed_encodings: t.Set[str] = client_encodings & scope["state"]["app"].encoding
    if allowed_encodings:
        encoding = next(iter(allowed_encodings))

    if encoding:
        encoded_headers.append((b"content-encoding", encoding.encode()))
        body = gzip.compress(body)

    response_start = {
        "type": "http.response.start",
        "status": response.status,
        "headers": encoded_headers,
    }
    await send(response_start)

    response_body = {
        "type": "http.response.body",
        "body": response.body.encode(),
        "more_body": False,
    }
    await send(response_body)


def router(request: Request) -> Response:
    match request.method, request.path:
        case "GET", "/":
            response = Response(
                headers={"content-type": "text/plain"},
                body="Hello, world!",
            )

        case "GET", path if (match := re.match(r"/echo/(\w+)$", path)):
            echo_str = match.group(1)
            response = Response(
                headers={"content-type": "text/plain"},
                body=echo_str,
            )

        case "GET", "/user-agent":
            response = Response(
                headers={"content-type": "text/plain"},
                body=request.headers["user-agent"],
            )

        case "GET", path if (match := re.match(r"/files/(\w+)$", path)):
            file_name = match.group(1)
            file = request.scope["state"]["app"].directory / file_name
            response = Response(
                headers={"content-type": "application/octet-stream"},
                body=file.read_text(),
            )

        case "POST", path if (match := re.match(r"/files/(\w+)$", path)):
            file_name = match.group(1)
            file = request.scope["state"]["app"].directory / file_name
            file.write_text(request.body)
            response = Response(
                status=201,
                headers={"content-type": "text/plain"},
                body="OK",
            )

        case _:
            response = Response(
                status=404,
                headers={"content-type": "text/plain"},
                body="Not Found",
            )
    return response


async def http_handler(
    scope: ut.HTTPScope,
    receive: t.Callable[[], t.Awaitable[HTTPReceiveEvent]],
    send: t.Callable[[HTTPSendEvent], t.Awaitable[None]],
) -> None:
    """
    Args:
        scope: http scope
        receive: an asynchronous callable that returns a HTTPReceiveEvent
        send: an asynchronous callable that sends a HTTPSendEvent

    Returns:
        None
    """

    while True:
        event = await receive()

        if event["type"] == "http.request":
            event: ut.HTTPRequestEvent
            if not event["more_body"]:
                break  # proceed to sending the response

        elif event["type"] == "http.disconnect":
            event: ut.HTTPDisconnectEvent
            send_event: ut.HTTPDisconnectEvent = {
                "type": "http.disconnect",
            }
            await send(send_event)
            return  # connection is closed

        else:
            raise TypeError(f"Unexpected event type: {type(event)}")

    request = Request(scope, body=event["body"])
    response: Response = router(request)
    await send_response(scope, request, response, send)


async def lifespan_handler(
    scope: ut.LifespanScope,
    receive: t.Callable[[], t.Awaitable[LifeSpanReceiveEvent]],
    send: t.Callable[[LifeSpanSendEvent], t.Awaitable[None]],
) -> None:
    """
    Args:
        scope: a connection that lasts the lifetime of the application
        receive: an asynchronous callable that returns a LifeSpanReceiveEvent
        send: an asynchronous callable that sends a LifeSpanSendEvent

    Returns:
        None
    """
    while True:
        event = await receive()
        if event["type"] == "lifespan.startup":
            event: ut.LifespanStartupEvent
            send_event: ut.LifespanStartupCompleteEvent = {"type": "lifespan.startup.complete"}
            await send(send_event)
        elif event["type"] == "lifespan.shutdown":
            event: ut.LifespanShutdownEvent
            send_event: ut.LifespanShutdownCompleteEvent = {"type": "lifespan.shutdown.complete"}
            await send(send_event)
            break  # break the loop as the application is shutting down and no more lifetime events are expected
        else:
            raise TypeError(f"Unexpected event type: {type(event)}")


class App:
    directory: Path
    encoding = {"gzip"}

    def __init__(self, directory: str):
        self.directory = Path(directory) if directory else Path.cwd()

    async def __call__(
        self,
        scope: ut.Scope,
        receive: ut.ASGIReceiveCallable,
        send: ut.ASGISendCallable,
    ) -> None:
        print(f"Beginning connection. Scope: ", scope)

        scope["state"] = {"app": self}

        if scope["type"] == "lifespan":
            scope: ut.LifespanScope
            await lifespan_handler(scope, receive, send)
        elif scope["type"] == "http":
            scope: ut.HTTPScope
            await http_handler(scope, receive, send)
        elif scope["type"] == "websocket":
            raise NotImplementedError(f"Unsupported scope type: {scope['type']}")
        else:
            raise NotImplementedError(f"Unsupported scope type: {scope['type']}")

        print(f"Ending connection")


@click.command()
@click.option("--directory")
def main(directory):
    app = App(directory=directory)

    uvicorn.run(
        app,
        port=4221,
        reload=False,
        log_level="debug",

        # jailbreak code-crafters anti-cheat tests
        server_header=False,
        date_header=False,
    )  # fmt: skip


if __name__ == "__main__":
    main()
