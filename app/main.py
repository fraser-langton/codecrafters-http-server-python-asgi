from typing import Awaitable, Callable, Union

import uvicorn
import uvicorn._types as ut

HTTPReceiveEvent = Union[
    ut.HTTPRequestEvent,
    ut.HTTPDisconnectEvent,
]

LifeSpanReceiveEvent = Union[
    ut.LifespanStartupEvent,
    ut.LifespanShutdownEvent,
]

HTTPSendEvent = Union[
    ut.HTTPResponseStartEvent,
    ut.HTTPResponseBodyEvent,
    ut.HTTPResponseTrailersEvent,
    ut.HTTPServerPushEvent,
    ut.HTTPDisconnectEvent,
]

LifeSpanSendEvent = Union[
    ut.LifespanStartupCompleteEvent,
    ut.LifespanStartupFailedEvent,
    ut.LifespanShutdownCompleteEvent,
    ut.LifespanShutdownFailedEvent,
]


async def http_handler(
    scope: ut.HTTPScope,
    receive: Callable[[], Awaitable[HTTPReceiveEvent]],
    send: Callable[[HTTPSendEvent], Awaitable[None]],
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
            send_event: ut.HTTPResponseStartEvent = {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
                "trailers": False,
            }
            await send(send_event)
            if not event["more_body"]:
                break

        elif event["type"] == "http.disconnect":
            event: ut.HTTPDisconnectEvent
            send_event: ut.HTTPDisconnectEvent = {
                "type": "http.disconnect",
            }
            await send(send_event)
            return  # connection is closed

        else:
            raise TypeError(f"Unexpected event type: {type(event)}")

    send_event: ut.HTTPResponseStartEvent = {
        "type": "http.response.start",
        "status": 200,
        "headers": [b"Content-Type", b"text/plain"],
        "trailers": False,
    }
    await send(send_event)

    send_event: ut.HTTPResponseBodyEvent = {
        "type": "http.response.body",
        "body": b"Hello, world!",
        "more_body": False,
    }
    await send(send_event)


async def lifespan_handler(
    scope: ut.LifespanScope,
    receive: Callable[[], Awaitable[LifeSpanReceiveEvent]],
    send: Callable[[LifeSpanSendEvent], Awaitable[None]],
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


async def app(scope: ut.Scope, receive: ut.ASGIReceiveCallable, send: ut.ASGISendCallable) -> None:
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
    uvicorn.run(app, port=4221)


if __name__ == "__main__":
    main()
