import pytest
from src.agent import route_intent, AgentState
from langchain_core.messages import HumanMessage

def test_route_intent_casual():
    state: AgentState = {"messages": [HumanMessage(content="hi there")]}
    assert route_intent(state) == "casual"
    
def test_route_intent_analytical():
    state: AgentState = {"messages": [HumanMessage(content="plot the top 5 noise complaints")]}
    assert route_intent(state) == "agent"

def test_route_intent_mixed():
    # Even if they say hi, if they ask for data, it goes to agent
    state: AgentState = {"messages": [HumanMessage(content="hi, can you give me the data for 311?")]}
    assert route_intent(state) == "agent"
