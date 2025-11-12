curl --request POST \
  --url https://sage.sre-ab.ru/mage/api/search \
  --header 'Authorization: Bearer '\
  --header 'Content-Type: application/json' \
  --header 'Source: token_sla_calc' \
  --header 'accept: */*' \
  --data '
{
  "query": "pql {group=\"ab1_kim\", system=\"oncall-prober-metrics\"} | stats sum(value)",
  "size": 100000,
  "startTime": "2025-11-11T00:00:00.000Z",
  "endTime": "2025-11-12T12:00:00.000Z"
}
'