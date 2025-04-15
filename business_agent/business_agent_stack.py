from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_s3_deployment as s3_deployment,
    aws_bedrock as bedrock,
    aws_opensearchserverless as opensearchserverless,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_glue as glue,
    aws_redshiftserverless as redshiftserverless,
    RemovalPolicy,
    Duration,
    CustomResource,
    CfnDeletionPolicy,
    CfnOutput
)
from aws_cdk.custom_resources import Provider
from constructs import Construct
import json
from random import randint
import os
class BusinessAgentStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create an S3 bucket for supplemental data
        supplemental_data_bucket = s3.Bucket(
            self,
            "SupplementalDataBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # Create an S3 bucket for storing internal reports
        internal_reports_bucket = s3.Bucket(
            self,
            "InternalReportsBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # Create an S3 bucket for storing research reports
        research_reports_bucket = s3.Bucket(
            self,
            "ResearchReportsBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # Create an S3 bucket for storing financial data
        financial_data_bucket = s3.Bucket(
            self,
            "FinancialDataBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Upload the internal reports to the S3 bucket
        internal_reports_deployment = s3_deployment.BucketDeployment(
            self,
            "InternalReportsDeployment",
            destination_bucket=internal_reports_bucket,
            sources=[s3_deployment.Source.asset("./data/internal_reports")]
        )

        # Upload the research reports to the S3 bucket
        research_reports_deployment = s3_deployment.BucketDeployment(
            self,
            "ResearchReportsDeployment",
            destination_bucket=research_reports_bucket,
            sources=[s3_deployment.Source.asset("./data/research_reports")],
            memory_limit=1024
        )

        # Upload the financial data to the S3 bucket
        financial_data_deployment = s3_deployment.BucketDeployment(
            self,
            "FinancialDataDeployment",
            destination_bucket=financial_data_bucket,
            destination_key_prefix="datalake/financial_data",
            sources=[s3_deployment.Source.asset("./data/financial_data")]
        )

        # Create a Glue Crawler role to crawl the financial data
        financial_data_crawler_role = iam.Role(
            self,
            "FinancialDataCrawlerRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com")
        )

        # Add managed policies for Glue service and S3 access
        financial_data_crawler_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole")
        )

        financial_data_crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["glue:StartCrawler"],
                resources=["*"]
            )
        )

        financial_data_bucket.grant_read(financial_data_crawler_role)

        # Create a Glue database
        financial_data_database = glue.CfnDatabase(
            self,
            "FinancialDataDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="financial_data_db",
                description="Database for financial data catalog"
            )
        )

        # Create a Glue Crawler to crawl the financial data
        financial_data_crawler = glue.CfnCrawler(
            self,
            "FinancialDataCrawler",
            role=financial_data_crawler_role.role_arn,
            database_name="financial_data_db",
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[glue.CfnCrawler.S3TargetProperty(
                    path=f"s3://{financial_data_bucket.bucket_name}/datalake/financial_data"
                )]
            ),
            name="financial-data-crawler"
        )

        financial_data_crawler.node.add_dependency(financial_data_database)
        financial_data_crawler.node.add_dependency(financial_data_deployment)

        # Create a role for a custom lambda function to start the crawler
        crawler_starter_lambda_role = iam.Role(
            self, "CrawlerStarterLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )

        crawler_starter_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )

        crawler_starter_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:StartCrawler",
                    "glue:GetCrawler"
                    ],
                resources=["*"]
            )
        )

        # Create a custom lambda function to start the crawler
        crawler_starter_lambda = lambda_.Function(
            self, "CrawlerStarterLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset("./lambda/crawler_initializer"),
            role=crawler_starter_lambda_role,
            timeout=Duration.minutes(5),
            environment={
                "CrawlerName": financial_data_crawler.name
            }
        )

        # Create the custom resource to start the crawler
        crawler_starter_resource = CustomResource(
            self, "CrawlerStarterResource",
            service_token=Provider(
                self, "CrawlerStarterProvider",
                on_event_handler=crawler_starter_lambda
            ).service_token
        )

        crawler_starter_resource.node.add_dependency(crawler_starter_lambda)
        crawler_starter_resource.node.add_dependency(financial_data_crawler)

        # Create a Redshift Serverless namespace
        redshift_namespace = redshiftserverless.CfnNamespace(
            self, "FinancialDataNamespace",
            namespace_name="financial-data-namespace",
            admin_username="admin_user",
            admin_user_password="Admin123!",
            db_name="financial_data_db",
        )

        # Create a Redshift Serverless workgroup
        redshift_workgroup = redshiftserverless.CfnWorkgroup(
            self, "FinancialDataWorkgroup",
            workgroup_name="financial-data-workgroup",
            namespace_name=redshift_namespace.namespace_name,
            base_capacity=32,  # Adjust capacity as needed for your workload
            enhanced_vpc_routing=False,
            publicly_accessible=False
        )

        # Add dependency to ensure namespace is created before the workgroup
        redshift_workgroup.add_dependency(redshift_namespace)


        # Create a collection in the AOSS domain
        collection_name = "business-agent-collection"

        # Create security policy for the AOSS collection
        security_policy = opensearchserverless.CfnSecurityPolicy(
            self, "CollectionEncryptionPolicy",
            name=f"encryption-policy-{randint(1000, 9999)}",
            type="encryption",
            policy=json.dumps({
                "Rules": [{
                    "ResourceType": "collection",
                    "Resource": [f"collection/{collection_name}"]
                }],
                "AWSOwnedKey": True
            })
        )

        security_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # Create network policy for the AOSS collection
        network_policy = opensearchserverless.CfnSecurityPolicy(
            self, "CollectionNetworkPolicy",
            name=f"network-policy-{randint(1000, 9999)}",
            type="network",
            policy=json.dumps([{
                "Rules": [{
                    "ResourceType": "collection",
                    "Resource": [f"collection/{collection_name}"]
                }, {
                    "ResourceType": "dashboard",
                    "Resource": [f"collection/{collection_name}"]
                }],
                "AllowFromPublic": True  # For demo purposes only
            }])
        )

        network_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # Create OpenSearch Serverless collection
        collection = opensearchserverless.CfnCollection(
            self,
            "BusinessAgentCollection",
            name=collection_name,
            type="VECTORSEARCH",
            description="Business Agent Collection",
        )
        
        collection.add_dependency(security_policy)
        collection.add_dependency(network_policy)


        # Create lambda function for index initialization
        index_init_lambda_role = iam.Role(
            self, "IndexInitializerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )

        # Create data access policy for the AOSS collection
        data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, "CollectionAccessPolicy",
            name=f"data-access-policy-{randint(1000, 9999)}",
            type="data",
            policy=json.dumps([{
                "Rules": [
                    {
                        "ResourceType": "index",
                        "Resource": [f"index/{collection_name}/*"],
                        "Permission": ["aoss:*"]
                    },
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{collection_name}"],
                        "Permission": ["aoss:*"]
                    }
                ],
                "Principal": [
                    index_init_lambda_role.role_arn,
                    f"arn:aws:iam::{self.account}:root"
                ]
            }])
        )

        data_access_policy.add_dependency(collection)
        data_access_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE


        research_reports_index = "research_reports_index"
        internal_reports_index = "internal_reports_index"

        # # Add requests_aws4auth layer for lambda function
        requests_layer = lambda_.LayerVersion(
            self, "RequestsLayer",
            code=lambda_.Code.from_asset("./layers/requests.zip")
        )

        index_init_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )

        index_init_lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "aoss:APIAccessAll",
                    "aoss:List*",
                    "aoss:Create*",
                    "aoss:Update*",
                    "aoss:Delete*",
                ],
                resources=["*"]
            )
        )

        index_init_lambda = lambda_.Function(
            self, "IndexInitializerFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset("./lambda/index_initializer"),
            environment={
                "COLLECTION_ENDPOINT": collection.attr_collection_endpoint,
                "INDICES": json.dumps([research_reports_index, internal_reports_index]),
                "REGION": self.region
            },
            timeout=Duration.minutes(5),
            layers=[requests_layer],
            role=index_init_lambda_role
        )

        index_init_lambda.node.add_dependency(collection)
        index_init_lambda.node.add_dependency(data_access_policy)

        index_init_trigger = CustomResource(
            self, "IndexInitTrigger",
            service_token=Provider(
                self, "IndexInitProvider",
                on_event_handler=index_init_lambda
            ).service_token
        )

        index_init_trigger.node.add_dependency(data_access_policy)

        # Create IAM role for Bedrock Knowledge Base
        knowledge_base_role = iam.Role(
            self, 'KnowledgeBaseRole',
            assumed_by=iam.ServicePrincipal('bedrock.amazonaws.com'),
        )

        # # Add S3 permissions to the role
        knowledge_base_role.add_to_policy(iam.PolicyStatement(
            actions=[
                's3:GetObject',
                's3:ListBucket',
                's3:PutObject',
                's3:DeleteObject'
            ],
            resources=[
                internal_reports_bucket.bucket_arn,
                f'{internal_reports_bucket.bucket_arn}/*',
                research_reports_bucket.bucket_arn,
                f'{research_reports_bucket.bucket_arn}/*',
                supplemental_data_bucket.bucket_arn,
                f'{supplemental_data_bucket.bucket_arn}/*'
            ],
        ))

        internal_reports_bucket.grant_read(knowledge_base_role)
        research_reports_bucket.grant_read(knowledge_base_role)
        supplemental_data_bucket.grant_read_write(knowledge_base_role)


        # Add OpenSearch permissions to the role
        knowledge_base_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'aoss:APIAccessAll'
            ],
            resources=[collection.attr_arn],
        ))

        # Add Bedrock permissions to the role
        knowledge_base_role.add_to_policy(iam.PolicyStatement(
            actions=[
                'bedrock:*',
                'glue:*',
                'redshift-serverless:*',
                'redshift-data:*',
                'sqlworkbench:*',
                's3:*'
            ],
            resources=['*'],
        ))

        # # Create Data Access Policy for Bedrock Knowledge Base
        bedrock_data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, 'BedrockDataAccessPolicy',
            name=f'bedrock-access-policy-{randint(1000, 9999)}',
            type='data',
            description='Data access policy for development',
            policy=json.dumps([
                {
                    'Rules': [
                        {
                            'ResourceType': 'collection',
                            'Resource': [f'collection/{collection_name}'],
                            'Permission': [
                                'aoss:CreateCollectionItems',
                                'aoss:DeleteCollectionItems',
                                'aoss:UpdateCollectionItems',
                                'aoss:DescribeCollectionItems',
                                'aoss:*'
                            ]
                        },
                        {
                            'ResourceType': 'index',
                            'Resource': [f"index/{collection_name}/*"],
                            'Permission': [
                                'aoss:CreateIndex',
                                'aoss:DeleteIndex',
                                'aoss:UpdateIndex',
                                'aoss:DescribeIndex',
                                'aoss:ReadDocument',
                                'aoss:WriteDocument',
                                'aoss:*'
                            ]
                        }
                    ],
                    'Principal': [
                        knowledge_base_role.role_arn,
                        f'arn:aws:iam::{self.account}:root'
                    ],
                    'Description': 'Combined access policy for both collection and index operations'
                }
            ])
        )

        # Add dependencies
        bedrock_data_access_policy.add_dependency(collection)
        bedrock_data_access_policy.cfn_options.deletion_policy = CfnDeletionPolicy.DELETE

        # Create Knowledge Base
        with open("./structured_knoledgebase_artifacts/curated_queries.json", "r") as f:
            curated_queries = json.load(f)
        
        with open("./structured_knoledgebase_artifacts/table_column_description.json", "r") as f:
            table_column_description = json.load(f)

        financial_data_kb_name = 'financial-data-knowledge-base'
        financial_data_kb = bedrock.CfnKnowledgeBase(
            self, 'FinancialDataKb',
            name=financial_data_kb_name,
            role_arn=knowledge_base_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="SQL",
                sql_knowledge_base_configuration=bedrock.CfnKnowledgeBase.SqlKnowledgeBaseConfigurationProperty(
                    type="REDSHIFT",
                    redshift_configuration=bedrock.CfnKnowledgeBase.RedshiftConfigurationProperty(
                        query_engine_configuration=bedrock.CfnKnowledgeBase.RedshiftQueryEngineConfigurationProperty(
                            type="SERVERLESS",
                            serverless_configuration=bedrock.CfnKnowledgeBase.RedshiftServerlessConfigurationProperty(
                                auth_configuration=bedrock.CfnKnowledgeBase.RedshiftServerlessAuthConfigurationProperty(
                                    type="IAM",
                                ),
                                workgroup_arn=redshift_workgroup.attr_workgroup_workgroup_arn
                            )
                        ),
                        storage_configurations=[bedrock.CfnKnowledgeBase.RedshiftQueryEngineStorageConfigurationProperty(
                            type="AWS_DATA_CATALOG",
                            aws_data_catalog_configuration=bedrock.CfnKnowledgeBase.RedshiftQueryEngineAwsDataCatalogStorageConfigurationProperty(
                                table_names=["financial_data_db.*"]
                            )
                        )],
                        query_generation_configuration=bedrock.CfnKnowledgeBase.QueryGenerationConfigurationProperty(
                            execution_timeout_seconds=200,
                            generation_context=bedrock.CfnKnowledgeBase.QueryGenerationContextProperty(
                                curated_queries=[
                                    bedrock.CfnKnowledgeBase.CuratedQueryProperty(
                                        natural_language=query["naturalLanguage"],
                                        sql=query["sqlQuery"]
                                    ) for query in curated_queries["queryPairs"]
                                ],
                                tables=[
                                    bedrock.CfnKnowledgeBase.QueryGenerationTableProperty(
                                        name=f"awsgluecatalog.financial_data_db.{table_name}",
                                        columns=[
                                            bedrock.CfnKnowledgeBase.QueryGenerationColumnProperty(
                                                name=column_name,
                                                description=column_description
                                            ) for column_name, column_description in table_columns.items()
                                        ],
                                        description=f"Table containing {table_name} information"
                                    ) for table_name, table_columns in table_column_description.items()
                                ]
                            )
                        )
                    )
                )
            )
        )

        # Add dependencies to ensure resources are created in correct order
        financial_data_kb.node.add_dependency(redshift_workgroup)
        financial_data_kb.node.add_dependency(crawler_starter_resource)
        financial_data_kb.node.add_dependency(knowledge_base_role)

        financial_data_data_source = bedrock.CfnDataSource(
            self, 'FinancialDataDataSource',
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="REDSHIFT_METADATA",
            ),
            knowledge_base_id=financial_data_kb.attr_knowledge_base_id,
            name='financial-data-datasource',
            description='Data source for financial data',
        )

        financial_data_data_source.node.add_dependency(financial_data_kb)
        
        internal_reports_kb_name = 'internal-reports-knowledge-base'
        internal_reports_kb = bedrock.CfnKnowledgeBase(
            self, 'InternalReportsKb',
            name=internal_reports_kb_name,
            role_arn=knowledge_base_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type='VECTOR',
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f'arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0',
                    supplemental_data_storage_configuration=bedrock.CfnKnowledgeBase.SupplementalDataStorageConfigurationProperty(
                        supplemental_data_storage_locations=[
                            bedrock.CfnKnowledgeBase.SupplementalDataStorageLocationProperty(
                                supplemental_data_storage_location_type="S3",
                                s3_location=bedrock.CfnKnowledgeBase.S3LocationProperty(
                                    uri=f"s3://{supplemental_data_bucket.bucket_name}"
                                )
                            )]
                    )
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type='OPENSEARCH_SERVERLESS',
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=collection.attr_arn,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        metadata_field='metadata',
                        text_field='content',
                        vector_field='content_embedding',
                    ),
                    vector_index_name=internal_reports_index,
                ),
            ),
        )

        internal_reports_kb.node.add_dependency(knowledge_base_role)
        internal_reports_kb.node.add_dependency(index_init_trigger)
        internal_reports_kb.node.add_dependency(bedrock_data_access_policy)

        # Create data source that points to our document bucket
        internal_reports_data_source = bedrock.CfnDataSource(
            self, 'BedrockDataSource',
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=internal_reports_bucket.bucket_arn,
                ),
                type='S3'
            ),
            knowledge_base_id=internal_reports_kb.attr_knowledge_base_id,
            name='internal-reports-datasource',
            description='Data source for internal reports',
            data_deletion_policy='RETAIN',
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy='HIERARCHICAL',
                    hierarchical_chunking_configuration=bedrock.CfnDataSource.HierarchicalChunkingConfigurationProperty(
                        level_configurations=[
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=1000
                            ),
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=200
                            )
                        ],
                        overlap_tokens=60
                    )
                ),
                parsing_configuration=bedrock.CfnDataSource.ParsingConfigurationProperty(
                    parsing_strategy='BEDROCK_FOUNDATION_MODEL',
                    bedrock_foundation_model_configuration=bedrock.CfnDataSource.BedrockFoundationModelConfigurationProperty(
                        model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                        parsing_modality="MULTIMODAL"
                    )
                )
            )
        )

        internal_reports_data_source.node.add_dependency(internal_reports_kb)
        internal_reports_data_source.node.add_dependency(internal_reports_deployment)

        research_reports_kb_name = 'research-reports-knowledge-base'
        research_reports_kb = bedrock.CfnKnowledgeBase(
            self, 'ResearchReportsKb',
            name=research_reports_kb_name,
            role_arn=knowledge_base_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type='VECTOR',
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f'arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0',
                    supplemental_data_storage_configuration=bedrock.CfnKnowledgeBase.SupplementalDataStorageConfigurationProperty(
                        supplemental_data_storage_locations=[
                            bedrock.CfnKnowledgeBase.SupplementalDataStorageLocationProperty(
                                supplemental_data_storage_location_type="S3",
                                s3_location=bedrock.CfnKnowledgeBase.S3LocationProperty(
                                    uri=f"s3://{supplemental_data_bucket.bucket_name}"
                                )
                            )]
                    )
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type='OPENSEARCH_SERVERLESS',
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=collection.attr_arn,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        metadata_field='metadata',
                        text_field='content',
                        vector_field='content_embedding',
                    ),
                    vector_index_name=research_reports_index,
                ),
            ),
        )

        research_reports_kb.node.add_dependency(knowledge_base_role)
        research_reports_kb.node.add_dependency(index_init_trigger)
        research_reports_kb.node.add_dependency(bedrock_data_access_policy)

        # Create data source that points to our document bucket
        research_reports_data_source = bedrock.CfnDataSource(
            self, 'ResearchReportsDataSource',
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=research_reports_bucket.bucket_arn,
                ),
                type='S3'
            ),
            knowledge_base_id=research_reports_kb.attr_knowledge_base_id,
            name='research-reports-datasource',
            description='Data source for research reports',
            data_deletion_policy='RETAIN',
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy='HIERARCHICAL',
                    hierarchical_chunking_configuration=bedrock.CfnDataSource.HierarchicalChunkingConfigurationProperty(
                        level_configurations=[
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=1000
                            ),
                            bedrock.CfnDataSource.HierarchicalChunkingLevelConfigurationProperty(
                                max_tokens=200
                            )
                        ],
                        overlap_tokens=60
                    )
                ),
                parsing_configuration=bedrock.CfnDataSource.ParsingConfigurationProperty(
                    parsing_strategy='BEDROCK_FOUNDATION_MODEL',
                    bedrock_foundation_model_configuration=bedrock.CfnDataSource.BedrockFoundationModelConfigurationProperty(
                        model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                        parsing_modality="MULTIMODAL"
                    )
                )
            )
        )

        research_reports_data_source.node.add_dependency(research_reports_kb)
        research_reports_data_source.node.add_dependency(research_reports_deployment)

        # Use the existing KB sync Lambda with modifications
        kb_sync_lambda = lambda_.Function(
            self, 'KBSyncFunction',
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler='index.handler',
            code=lambda_.Code.from_asset('lambda/kb_sync'),
            environment={
                'KNOWLEDGE_BASE_ID': json.dumps([
                    # internal_reports_kb.attr_knowledge_base_id, 
                    # research_reports_kb.attr_knowledge_base_id, 
                    financial_data_kb.attr_knowledge_base_id]),
                'DATA_SOURCE_ID': json.dumps([
                    # internal_reports_data_source.attr_data_source_id, 
                    # research_reports_data_source.attr_data_source_id, 
                    financial_data_data_source.attr_data_source_id]),
                'REGION': self.region
            },
            timeout=Duration.minutes(5)
        )

        # Grant permissions to sync the knowledge base
        kb_sync_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=[
                'bedrock:StartIngestionJob',
                'bedrock:GetIngestionJob',
                'bedrock:ListIngestionJobs',
            ],
            resources=['*'],
        ))

        # Custom resource to sync the knowledge base
        kb_sync_resource = CustomResource(
            self, 'KBSyncResource',
            service_token=Provider(
                self, "KBSyncProvider",
                on_event_handler=kb_sync_lambda
            ).service_token
        )

        kb_sync_resource.node.add_dependency(research_reports_kb)
        kb_sync_resource.node.add_dependency(internal_reports_kb)
        kb_sync_resource.node.add_dependency(research_reports_data_source)
        kb_sync_resource.node.add_dependency(internal_reports_data_source)
        kb_sync_resource.node.add_dependency(financial_data_kb)
        kb_sync_resource.node.add_dependency(financial_data_data_source)

        # Create a lambda role for the redshift authorizer
        redshift_authorizer_lambda_role = iam.Role(
            self, 'RedshiftAuthorizerLambdaRole',
            assumed_by=iam.ServicePrincipal('lambda.amazonaws.com')
        )
        
        redshift_authorizer_lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonRedshiftFullAccess")
        )

        # Create a Lambda function for the Redshift authorizer
        redshift_authorizer_lambda = lambda_.Function(
            self, 'RedshiftAuthorizerFunction',
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler='index.handler',
            code=lambda_.Code.from_asset('lambda/redshift_authorizer'),
            environment={
                'REDSHIFT_SERVERLESS_WORKGROUP': redshift_workgroup.attr_workgroup_workgroup_arn,
                'REDSHIFT_DATABASE': 'awsdatacatalog',
                'BEDROCK_KB_ROLE_NAME': knowledge_base_role.role_name
            },
            role=redshift_authorizer_lambda_role,
            timeout=Duration.minutes(5)
        )

        redshift_authorizer_lambda.node.add_dependency(kb_sync_resource)
        
        # Create a custom resource trigger for the redshift authorizer
        redshift_authorizer_resource = CustomResource(
            self, 'RedshiftAuthorizerResource',
            service_token=Provider(
                self, 'RedshiftAuthorizerProvider',
                on_event_handler=redshift_authorizer_lambda
            ).service_token
        )

        redshift_authorizer_resource.node.add_dependency(redshift_authorizer_lambda)
        redshift_authorizer_resource.node.add_dependency(knowledge_base_role)
        redshift_authorizer_resource.node.add_dependency(redshift_workgroup)


        CfnOutput(
            self, 'financial_data_kb_id',
            value=financial_data_kb.attr_knowledge_base_id,
            description='The ID of the financial data knowledge base'
        )
        
        CfnOutput(
            self, 'internal_reports_kb_id',
            value=internal_reports_kb.attr_knowledge_base_id,
            description='The ID of the internal reports knowledge base'
        )
        
        CfnOutput(
            self, 'research_reports_kb_id',
            value=research_reports_kb.attr_knowledge_base_id,
            description='The ID of the research reports knowledge base'
        )
        