import boto3
import os
import json
import cfnresponse
import time
from datetime import datetime


def handler(event, context):
    try:
        print(f"Starting KB sync handler with event: {event}")

        kb_ids = json.loads(os.environ['KNOWLEDGE_BASE_ID'])
        ds_ids = json.loads(os.environ['DATA_SOURCE_ID'])
        region = os.environ['REGION']

        # Get document ID from event
        document_id = None
        if 'ResourceProperties' in event and 'DocumentId' in event['ResourceProperties']:
            document_id = event['ResourceProperties']['DocumentId']
        elif 'RequestId' in event:
            document_id = event['RequestId']

        bedrock = boto3.client('bedrock-agent', region_name=region)

        if event['RequestType'] in ['Create', 'Update']:
            # Start ingestion job
            for kb_id, ds_id in zip(kb_ids, ds_ids):
                response = bedrock.start_ingestion_job(
                    knowledgeBaseId=kb_id,
                    dataSourceId=ds_id
                )

                ingestion_job_id = response['ingestionJob']['ingestionJobId']
                print(f"Started ingestion job: {ingestion_job_id}")


            # Wait for job to complete (may timeout for large datasets)
            max_wait_time = 240  # seconds
            wait_interval = 10  # seconds
            elapsed_time = 0
            final_status = 'UNKNOWN'

            while elapsed_time < max_wait_time:
                all_successful = True
                
                for kb_id, ds_id in zip(kb_ids, ds_ids):
                    job_status = bedrock.get_ingestion_job(
                        knowledgeBaseId=kb_id,
                        dataSourceId=ds_id,
                        ingestionJobId=ingestion_job_id
                    )

                    status = job_status['ingestionJob']['status']
                    print(f"Job status: {status}")
                    final_status = status
                    
                    if status != 'SUCCESS':
                        all_successful = False
                
                if all_successful:
                    print("All ingestion jobs completed successfully!")
                    break
                    
                time.sleep(wait_interval)
                elapsed_time += wait_interval

            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'IngestionJobId': ingestion_job_id,
                'Status': final_status if elapsed_time < max_wait_time else 'STILL_RUNNING'
            })
        else:
            # Nothing to do for Delete
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
    except Exception as e:
        print(f"Error in KB sync: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': str(e)})
