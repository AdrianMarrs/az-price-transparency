{# Fails for any row whose item is over 350 KB: DynamoDB refuses items over 400 KB, and
   the margin covers attribute names and type overhead in DynamoDB's own size count. #}
{% test under_dynamodb_item_limit(model, column_name, max_bytes=350000) %}
select * from {{ model }} where {{ column_name }} > {{ max_bytes }}
{% endtest %}
