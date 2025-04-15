import boto3
import cfnresponse
import time
import json
import os

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")  # Log the entire event for debugging
    
    if event['RequestType'] in ['Create', 'Update']:
        try:
            # Make sure the property exists and extract it correctly
            resource_properties = event.get('ResourceProperties', {})
            crawler_name = os.environ.get('CrawlerName')
            
            if not crawler_name:
                raise ValueError("CrawlerName property is missing or empty")
                
            print(f"Starting crawler: {crawler_name}")
            
            glue_client = boto3.client('glue')
            
            # Wait a bit to ensure the crawler is fully created
            time.sleep(10)
            
            # Start the crawler
            glue_client.start_crawler(Name=crawler_name)
            print(f"Crawler {crawler_name} started successfully")
            
            # Wait for the crawler to complete
            max_wait_time = 20 * 60  # 20 minutes maximum wait time
            wait_interval = 30  # Check status every 30 seconds
            total_wait_time = 0
            
            while total_wait_time < max_wait_time:
                response = glue_client.get_crawler(Name=crawler_name)
                crawler_state = response['Crawler']['State']
                
                print(f"Crawler state: {crawler_state}")
                
                if crawler_state == 'READY':  # Crawler is done running
                    print(f"Crawler {crawler_name} completed successfully")
                    cfnresponse.send(event, context, cfnresponse.SUCCESS, 
                                    {'Message': 'Crawler completed successfully'})
                    # Wait for 60 seconds for propagation
                    time.sleep(60)
                    return
                
                # If still running, wait and check again
                time.sleep(wait_interval)
                total_wait_time += wait_interval
            
            # If we get here, we timed out
            raise TimeoutError(f"Crawler {crawler_name} did not complete within {max_wait_time} seconds")
            
        except Exception as e:
            print(f"Error with crawler operation: {str(e)}")
            cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': str(e)})
    else:
        # For Delete requests
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {'Message': 'Nothing to do for Delete'})