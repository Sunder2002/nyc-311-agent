from agent import app as graph_app
from langchain_core.messages import HumanMessage
from tools import set_df
import pandas as pd

print("Loading data...")
df = pd.read_csv("311_Service_Requests_from_2010_to_Present.csv", low_memory=False)
set_df(df)

state = {"messages": [HumanMessage(content="What are the top 3 complaint types?")]}
print("Invoking agent...")
result = graph_app.invoke(state, config={"recursion_limit": 10})

for msg in result["messages"]:
    print(f"[{msg.type}]: {msg.content}")
