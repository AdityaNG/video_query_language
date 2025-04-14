# Video Perception

The script takes a video as input. Then it iterates through the video and tags each frame (at the specified FPS) with the answers to the queries in the YAML config. We use the factory method to generate the pydantic structures and make the structured LLM calls

```
python main.py --video results/video_full.mp4 --config default_config.yaml
```

`default_config.yaml`: structure
```
queries:
  - query: "Is the bear visible?"
    options: ["yes", "no"]
  - query: "What is the color of the bear?"
    options: ["white", "black", "red"]
fps: 1.0
tile_frames: [3, 3]
```

# Langchain structured outputs

```
import getpass
import os

if not os.environ.get("OPENAI_API_KEY"):
  os.environ["OPENAI_API_KEY"] = getpass.getpass("Enter API key for OpenAI: ")

from langchain.chat_models import init_chat_model

model = init_chat_model("gpt-4o-mini", model_provider="openai")

model.invoke("Hello, world!")

from typing import Optional

from pydantic import BaseModel, Field


# Pydantic
class Joke(BaseModel):
    """Joke to tell user."""

    setup: str = Field(description="The setup of the joke")
    punchline: str = Field(description="The punchline to the joke")
    rating: Optional[int] = Field(
        default=None, description="How funny the joke is, from 1 to 10"
    )


structured_llm = llm.with_structured_output(Joke)

structured_llm.invoke("Tell me a joke about cats")
# Joke(setup='Why was the cat sitting on the computer?', punchline='Because it wanted to keep an eye on the mouse!', rating=7)


from typing import Optional

from typing_extensions import Annotated, TypedDict


# TypedDict
class Joke(TypedDict):
    """Joke to tell user."""

    setup: Annotated[str, ..., "The setup of the joke"]

    # Alternatively, we could have specified setup as:

    # setup: str                    # no default, no description
    # setup: Annotated[str, ...]    # no default, no description
    # setup: Annotated[str, "foo"]  # default, no description

    punchline: Annotated[str, ..., "The punchline of the joke"]
    rating: Annotated[Optional[int], None, "How funny the joke is, from 1 to 10"]


structured_llm = llm.with_structured_output(Joke)

structured_llm.invoke("Tell me a joke about cats")
# {'setup': 'Why was the cat sitting on the computer?',
 'punchline': 'Because it wanted to keep an eye on the mouse!',
 'rating': 7}
```