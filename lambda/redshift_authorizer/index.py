import boto3
import logging
import os
from botocore.exceptions import ClientError
import json
import base64

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Lambda function to grant usage permissions on AWS Data Catalog to a specified IAM role
    by executing a query in Redshift Serverless Query Editor using username and password.
    """
    try:
        # Get configuration from environment variables
        workgroup_name = os.environ.get('REDSHIFT_SERVERLESS_WORKGROUP')
        database_name = os.environ.get('REDSHIFT_DATABASE')
        role_name = os.environ.get('BEDROCK_KB_ROLE_NAME', 'bedrock-knowledgebase-role')
            
        # Initialize Redshift Data API client
        redshift_client = boto3.client('redshift-data')
        
        # The query to grant usage permissions
        query = f'GRANT USAGE ON DATABASE "awsdatacatalog" TO "IAMR:{role_name}"'
        
        # Execute the query using Redshift Data API for Serverless with credentials
        response = redshift_client.execute_statement(
            WorkgroupName=workgroup_name,
            Database=database_name,
            Sql=query
        )
        
        statement_id = response['Id']
        logger.info(f"Query execution started with statement ID: {statement_id}")
        
        return {
            'statusCode': 200,
            'body': f"Grant usage query submitted to Redshift Serverless. Statement ID: {statement_id}"
        }
        
    except ClientError as e:
        logger.error(f"AWS client error: {str(e)}")
        return {
            'statusCode': 500,
            'body': f"AWS client error: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error executing grant permission: {str(e)}")
        return {
            'statusCode': 500,
            'body': f"Error executing grant permission: {str(e)}"
        }