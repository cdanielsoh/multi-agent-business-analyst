import json

with open('structured_knoledgebase_artifacts/table_column_description.json', 'r') as f:
    table_column_description = json.load(f)

print(table_column_description)

test = [
    {
        "name": table_name,
        "columns": [
            {
                "name": column_name,
                "description": column_description
            } for column_name, column_description in table_columns.items()
        ],
        "description": f"Table containing {table_name} information"
    } for table_name, table_columns in table_column_description.items()
]

print(test)