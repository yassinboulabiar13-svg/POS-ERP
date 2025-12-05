#!/usr/bin/env bash
BASE="http://127.0.0.1:5003"

echo "Health:"
curl -s $BASE/health | jq

echo
echo "Initiate payment (card) - cart-100:"
curl -s -X POST $BASE/payments/initiate -H "Content-Type: application/json" -d '{"client_payment_id":"cart-100-pay-1","amount":120.0,"mode":"card"}' | jq

echo
echo "Initiate payment (cash) - cart-101:"
curl -s -X POST $BASE/payments/initiate -H "Content-Type: application/json" -d '{"client_payment_id":"cart-101-pay-1","amount":50.0,"mode":"cash"}' | jq

echo
echo "List payments:"
curl -s $BASE/payments | jq

# Authorize the card payment (use card number ending with even digit -> accepted)
echo
echo "Authorize payment 1 (card):"
curl -s -X POST $BASE/payments/authorize/1 -H "Content-Type: application/json" -d '{"card":{"number":"4242424242424242","expiry":"12/30","cvv":"123"}}' | jq

echo
echo "Confirm payment 1:"
curl -s -X POST $BASE/payments/confirm/1 | jq

echo
echo "Get payment 1:"
curl -s $BASE/payments/1 | jq

echo
echo "Confirm cash payment (should record directly):"
curl -s -X POST $BASE/payments/confirm/2 | jq

echo
echo "List ERP Queue (pending syncs):"
curl -s $BASE/admin/erp_queue | jq

echo
echo "Get receipt for payment 1 (fetch receipt number from payment):"
RCPT=$(curl -s $BASE/payments/1 | jq -r '.receipt.receipt_number')
echo "Receipt number: $RCPT"
curl -s $BASE/receipts/$RCPT | jq
