# Purchase Payment Request - Odoo 14

Version: 14.0.1.0.0
Author: Ashraf Shora

## Main behavior
- Payment Request collects confirmed Purchase Orders automatically.
- Criteria:
  - Purchase Order state = purchase
  - advance_percentage > 0
  - same company
  - optional date_from/date_to based on date_approve
  - POs already used in non-draft/non-rejected Payment Requests are excluded
- Lines are read-only in the form; manual creation/deletion is disabled in the UI.
- Refresh Purchase Orders works only in Draft.
- Purchase Order is a clickable Many2one link.
- Analytic Account is read from purchase.order.Analytic_id.
- Workflow: Draft -> Submitted -> Finance Review -> GM Approval -> Approved.
- Revision and Rejection are supported.
- PDF report is included.

## Important
This module assumes your Odoo 14 purchase.order has:
    Analytic_id = account.analytic.account

If your field is named differently (for example analytic_account_id or analytic_id), change:
    related="purchase_order_id.Analytic_id"

The module also assumes advance_percentage is a custom field on purchase.order; this module creates it.

## Installation
1. Copy the module folder to your custom addons path.
2. Update Apps List.
3. Install "Purchase Payment Request".
