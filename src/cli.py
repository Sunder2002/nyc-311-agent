import sys
import uuid
import os
import logging
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent import app as graph_app

logging.basicConfig(level=logging.WARNING)

def main():
    print("=============================================")
    print(" NYC 311 Enterprise Data Agent - CLI Mode")
    print("=============================================")
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 15}
    
    while True:
        try:
            user_input = input("\n[You]: ")
            if user_input.lower() in ['exit', 'quit']:
                break
                
            if not user_input.strip():
                continue
                
            print("\n[Agent Thinking...]")
            
            state = {"messages": [HumanMessage(content=user_input)]}
            
            for event in graph_app.stream(state, config=config):
                for node_name, node_state in event.items():
                    messages = node_state.get('messages', [])
                    if not messages:
                        continue
                        
                    last_message = messages[-1]
                    
                    if isinstance(last_message, ToolMessage):
                        print(f"\n--- 🔍 CITATION (Tool Execution: {last_message.name}) ---")
                        content = last_message.content
                        if len(content) > 500:
                            content = content[:500] + "\n... [Truncated for CLI]"
                        print(content)
                        print("--------------------------------------------------\n")
                    elif isinstance(last_message, AIMessage) and last_message.content:
                        print(f"\n[Agent]:\n{last_message.content}\n")
                        
        except KeyboardInterrupt:
            print("\nExiting CLI...")
            break
        except Exception as e:
            if "402" in str(e) or "Insufficient Balance" in str(e) or "quota" in str(e).lower():
                print("\n[ERROR] API Credit Exhausted. Please update GOOGLE_API_KEY in .env.")
            else:
                print(f"\n[ERROR] {e}")

if __name__ == "__main__":
    main()
