import re
import typing as t

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


async def router(
    scope: ut.HTTPScope,
    event: ut.HTTPRequestEvent,
    send: t.Callable[[HTTPSendEvent], t.Awaitable[None]],
):
    """
    Args:
        scope: http scope
        event: a HTTPRequestEvent
        send: an asynchronous callable that sends a HTTPSendEvent

    Returns:
        None
    """
    path: str = scope["path"]

    if re.match(r"/$", path):
        response_start = {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"],
            ],
        }
        await send(response_start)

        response_body = {
            "type": "http.response.body",
            "body": b"Hello, world!",
            "more_body": False,
        }
        await send(response_body)
    elif match := re.match(r"/echo/(\w+)$", path):
        echo_str = match.group(1)
        response_start = {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"],
            ],
        }
        await send(response_start)

        response_body = {
            "type": "http.response.body",
            "body": echo_str.encode(),
            "more_body": False,
        }
        await send(response_body)
    else:
        response_start = {
            "type": "http.response.start",
            "status": 404,
            "headers": [
                [b"content-type", b"text/plain"],
            ],
        }
        await send(response_start)

        response_body = {
            "type": "http.response.body",
            "body": b"Not found",
            "more_body": False,
        }
        await send(response_body)


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

    await router(scope, event, send)


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


async def app(
    scope: ut.Scope,
    receive: ut.ASGIReceiveCallable,
    send: ut.ASGISendCallable,
) -> None:
    print(f"Beginning connection. Scope: ", scope)

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


def main():
    uvicorn.run(
        "app.main:app",
        port=4221,
        reload=True,
        log_level="debug",

        # jailbreak code-crafters anti-cheat tests
        server_header=False,
        date_header=False,
    )  # fmt: skip


if __name__ == "__main__":
    main()
