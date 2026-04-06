import contextlib

with contextlib.suppress(ImportError):
    from stroma.adapters.langgraph import LangGraphAdapter as LangGraphAdapter
    from stroma.adapters.langgraph import stroma_langgraph_node as stroma_langgraph_node

with contextlib.suppress(ImportError):
    from stroma.adapters.deepagents import DeepAgentsAdapter as DeepAgentsAdapter
    from stroma.adapters.deepagents import stroma_deepagents_node as stroma_deepagents_node

with contextlib.suppress(ImportError):
    from stroma.adapters.crewai import CrewAIAdapter as CrewAIAdapter
    from stroma.adapters.crewai import stroma_crewai_step as stroma_crewai_step
