"""Fail closed before Presidio 2.2.364 catches regex TimeoutError.

No logging hooks, global monkey patches, retries, or shared failure flags.
PatternRecognizer's compiled_regex assignment protocol is the integration point;
dependency upgrades must revalidate it. Pattern text, flags, timeout arguments,
match objects, scores and recognizer identities are unchanged.
Instance-local validation callables can separately convert swallowed timeouts.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from presidio_analyzer import Pattern, PatternRecognizer, RecognizerRegistry


class L3DependencyTimeoutError(RuntimeError):
    """Incomplete dependency analysis; contains no input or exception text."""

    def __init__(self) -> None:
        super().__init__("L3_DEPENDENCY_TIMEOUT")


class _TimeoutMatcher:
    def __init__(self, matcher: Any) -> None:
        self._matcher = matcher

    def finditer(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[Any]:
        # Catch both eager finditer failure and lazy next() failure, including
        # timeout after earlier matches. Each invocation owns its own iterator.
        try:
            yield from self._matcher.finditer(*args, **kwargs)
        except TimeoutError:
            # Not a TimeoutError subclass: Presidio must not swallow it.
            raise L3DependencyTimeoutError() from None


class _FailClosedPattern(Pattern):
    @property
    def compiled_regex(self) -> Any:
        return self._compiled_regex

    @compiled_regex.setter
    def compiled_regex(
        self,
        matcher: Any,
    ) -> None:
        self._compiled_regex = (
            matcher
            if matcher is None or isinstance(matcher, _TimeoutMatcher)
            else _TimeoutMatcher(matcher)
        )


def protect_patterns(
    registry: RecognizerRegistry,
) -> None:
    """Detach class-level built-in PATTERNS and protect future recompilations."""
    for recognizer in registry.recognizers:
        # Local parser recognizers have no compiled pattern protocol.
        # Their failures propagate through the service request boundary.
        if not isinstance(recognizer, PatternRecognizer):
            continue
        dynamic_recognizer = cast(Any, recognizer)
        patterns: list[Pattern] = list(dynamic_recognizer.patterns)
        dynamic_recognizer.patterns = [
            _FailClosedPattern(
                pattern.name,
                pattern.regex,
                pattern.score,
            )
            for pattern in patterns
        ]


@dataclass(frozen=True, repr=False)
class TimeoutCallable:
    """Convert validator timeouts before the dependency can log/swallow them."""

    callback: Callable[..., Any]

    def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        try:
            return self.callback(*args, **kwargs)
        except TimeoutError:
            raise L3DependencyTimeoutError() from None


def protect_number_validators(registry: RecognizerRegistry) -> None:
    """Convert numeric producer validation timeouts before Presidio swallows them."""
    targets = frozenset(("KR_RRN", "KR_FRN", "KR_BRN", "KR_DRIVER_LICENSE"))
    for producer in registry.recognizers:
        if not isinstance(producer, PatternRecognizer):
            continue
        if len(producer.supported_entities) != 1 or producer.supported_entities[0] not in targets:
            continue
        instance = cast(Any, producer)
        instance.validate_result = protect_callable(instance.validate_result)


def protect_callable(
    callback: Callable[..., Any] | TimeoutCallable,
) -> TimeoutCallable:
    """Idempotent, instance-local; no request state or global interception."""
    return callback if isinstance(callback, TimeoutCallable) else TimeoutCallable(callback)
