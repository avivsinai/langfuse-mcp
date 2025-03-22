from datetime import datetime, timedelta, UTC
import json
import logging
import sys
import os
from langfuse import Langfuse

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("langfuse_debug")

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def print_json(data, title=None):
    """Helper to print JSON data with proper datetime handling"""
    if title:
        print(f"\n{title}")
    try:
        print(json.dumps(data, indent=2, cls=DateTimeEncoder))
    except Exception as e:
        print(f"Error serializing JSON: {e}")
        print(f"Raw data type: {type(data)}")
        print(f"Raw data: {data}")

def process_langfuse_response(response, item_name="items"):
    """Helper to process Langfuse response objects consistently"""
    if not response:
        return f"No {item_name} found"
    
    if hasattr(response, 'data') and isinstance(response.data, list):
        count = len(response.data)
        if count == 0:
            return f"No {item_name} found"
        
        # Convert first item to dict
        try:
            if count > 0:
                first_item = response.data[0].dict()
                return {
                    "count": count,
                    "first_item": first_item,
                    "all_ids": [item.id for item in response.data]
                }
        except Exception as e:
            return {
                "count": count,
                "error": f"Error processing response: {str(e)}",
                "raw": str(response.data[0])
            }
    
    return f"Unexpected response format for {item_name}: {response}"

def get_langfuse_client():
    """Create and return a Langfuse client with proper error handling"""
    # Get API keys from environment or use defaults
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-c6231d33-f98d-4393-9b28-4205f74984ae")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-e23afc03-982b-4f68-a4c2-f721af28691a")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    
    print(f"\nConnection settings:")
    print(f"- Host: {host}")
    print(f"- Public key: {public_key}")
    print(f"- Secret key: {'*' * 8 + secret_key[-4:] if secret_key else 'Not set'}")
    
    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            debug=True
        )
        return client
    except Exception as e:
        print(f"Error initializing Langfuse client: {str(e)}")
        logger.exception("Client initialization error")
        return None

def check_auth(client):
    """Check authentication with the Langfuse API"""
    if not client:
        return False
        
    try:
        print("\n=== Authentication Check ===")
        auth_ok = client.auth_check()
        print(f"Authentication successful: {auth_ok}")
        return auth_ok
    except Exception as e:
        print(f"Authentication failed: {str(e)}")
        logger.exception("Authentication check error")
        return False

def fetch_traces(client, from_time, to_time):
    """Fetch traces from Langfuse"""
    try:
        print("\n=== Traces ===")
        traces = client.fetch_traces(
            from_timestamp=from_time,
            to_timestamp=to_time,
            limit=10
        )
        result = process_langfuse_response(traces, "traces")
        print_json(result, "Traces summary")
        
        if isinstance(result, dict) and result.get("count", 0) > 0:
            trace_id = result["first_item"]["id"]
            print(f"\nFetching details for trace: {trace_id}")
            try:
                trace_details = client.get_trace(trace_id)
                if trace_details:
                    trace_dict = trace_details.dict()
                    print_json(trace_dict, "Trace details")
            except Exception as e:
                print(f"Error fetching trace details: {e}")
        return result
    except Exception as e:
        print(f"Error fetching traces: {str(e)}")
        logger.exception("Trace fetching error")
        return None

def fetch_observations(client, from_time, to_time):
    """Fetch observations/spans from Langfuse"""
    try:
        print("\n=== Observations (Spans) ===")
        observations = client.fetch_observations(
            from_start_time=from_time,
            to_start_time=to_time,
            type="SPAN",
            limit=10
        )
        result = process_langfuse_response(observations, "observations")
        print_json(result, "Observations summary")
        
        if isinstance(result, dict) and result.get("count", 0) > 0:
            obs_id = result["first_item"]["id"]
            print(f"\nFetching details for observation: {obs_id}")
            try:
                obs_details = client.get_observation(obs_id)
                if obs_details:
                    obs_dict = obs_details.dict()
                    print_json(obs_dict, "Observation details")
            except Exception as e:
                print(f"Error fetching observation details: {e}")
        return result
    except Exception as e:
        print(f"Error fetching observations: {str(e)}")
        logger.exception("Observation fetching error")
        return None

def fetch_sessions(client, from_time, to_time):
    """Fetch sessions from Langfuse"""
    try:
        print("\n=== Sessions ===")
        sessions = client.fetch_sessions(
            from_timestamp=from_time,
            to_timestamp=to_time,
            limit=10
        )
        result = process_langfuse_response(sessions, "sessions")
        print_json(result, "Sessions summary")
        
        if isinstance(result, dict) and result.get("count", 0) > 0 and "first_item" in result:
            session_id = result["first_item"]["id"]
            print(f"\nSession ID: {session_id}")
        return result
    except Exception as e:
        print(f"Error fetching sessions: {str(e)}")
        logger.exception("Session fetching error")
        return None

def main():
    print("=== Langfuse SDK Debug Tool ===")
    print(f"Python version: {sys.version}")
    
    # Initialize client
    client = get_langfuse_client()
    if not client:
        return
    
    # Check authentication
    if not check_auth(client):
        return
    
    # Time range for last 24 hours
    to_time = datetime.now(UTC)
    from_time = to_time - timedelta(hours=24)
    print(f"\nTime range: {from_time.isoformat()} to {to_time.isoformat()}")
    
    # Fetch data
    traces_result = fetch_traces(client, from_time, to_time)
    observations_result = fetch_observations(client, from_time, to_time)
    sessions_result = fetch_sessions(client, from_time, to_time)
    
    # Check for available API methods
    print("\n=== API Capability Check ===")
    available_methods = [method for method in dir(client) if not method.startswith('_')]
    print(f"Available client methods: {', '.join(sorted(available_methods))}")
    
    # Clean handling of generations
    try:
        print("\n=== Generations ===")
        # Check if the method exists
        if hasattr(client, 'get_generations') or hasattr(client, 'fetch_generations'):
            method_name = 'get_generations' if hasattr(client, 'get_generations') else 'fetch_generations'
            get_method = getattr(client, method_name)
            generations = get_method(
                limit=10
            )
            result = process_langfuse_response(generations, "generations")
            print_json(result, "Generations summary")
        else:
            print("Method for fetching generations not available in this version of the SDK")
    except Exception as e:
        print(f"Error fetching generations: {str(e)}")
        logger.exception("Generation fetching error")
    
    # Check for dataset capability
    try:
        print("\n=== Dataset Items ===")
        if hasattr(client, 'get_datasets') or hasattr(client, 'fetch_datasets'):
            method_name = 'get_datasets' if hasattr(client, 'get_datasets') else 'fetch_datasets'
            get_method = getattr(client, method_name)
            datasets = get_method(limit=5)
            datasets_result = process_langfuse_response(datasets, "datasets")
            print_json(datasets_result, "Datasets summary")
            
            if isinstance(datasets_result, dict) and datasets_result.get("count", 0) > 0:
                dataset_id = datasets_result["first_item"]["id"]
                print(f"\nFetching items for dataset: {dataset_id}")
                try:
                    if hasattr(client, 'get_dataset_items'):
                        dataset_items = client.get_dataset_items(dataset_id=dataset_id, limit=5)
                    else:
                        dataset_items = client.fetch_dataset_items(dataset_id=dataset_id, limit=5)
                    items_result = process_langfuse_response(dataset_items, "dataset items")
                    print_json(items_result, "Dataset items summary")
                except Exception as e:
                    print(f"Error fetching dataset items: {e}")
        else:
            print("Dataset functionality not available in this version of the SDK")
    except Exception as e:
        print(f"Dataset functionality check failed: {str(e)}")
        logger.exception("Dataset functionality check error")
    
    # Cleanup
    print("\n=== Cleanup ===")
    try:
        client.flush()
        client.shutdown()
        print("Langfuse client shutdown successfully")
    except Exception as e:
        print(f"Error during client shutdown: {str(e)}")

if __name__ == "__main__":
    main() 