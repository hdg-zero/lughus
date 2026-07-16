from __future__ import annotations


class LoopResult(str):
    """String subclass that carries usage metadata.

    Behaves exactly like a ``str`` (pass it to ``CompletionEvent(text=...)``,
    ``json.loads()``, etc.) but also exposes iteration count, wall-clock time,
    and token counters from the LLM calls.
    """

    iterations: int
    elapsed: float
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int

    def __new__(
        cls,
        text: str,
        *,
        iterations: int,
        elapsed: float,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int,
    ) -> LoopResult:
        instance = super().__new__(cls, text)
        instance.iterations = iterations
        instance.elapsed = elapsed
        instance.prompt_tokens = prompt_tokens
        instance.completion_tokens = completion_tokens
        instance.cached_tokens = cached_tokens
        return instance

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def uncached_prompt_tokens(self) -> int:
        return max(0, self.prompt_tokens - self.cached_tokens)

    def __getnewargs_ex__(self) -> tuple[tuple[str], dict]:
        return (str(self),), {
            "iterations": self.iterations,
            "elapsed": self.elapsed,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
        }

    def __copy__(self) -> LoopResult:
        return LoopResult(
            str(self),
            iterations=self.iterations,
            elapsed=self.elapsed,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cached_tokens=self.cached_tokens,
        )

    def __deepcopy__(self, memo: dict) -> LoopResult:
        return self.__copy__()
