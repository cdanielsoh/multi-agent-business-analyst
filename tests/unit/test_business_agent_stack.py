import aws_cdk as core
import aws_cdk.assertions as assertions

from business_agent.business_agent_stack import BusinessAgentStack

# example tests. To run these tests, uncomment this file along with the example
# resource in business_agent/business_agent_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = BusinessAgentStack(app, "business-agent")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
