# -*- coding: utf-8 -*-
import logging
import requests

from odoo import _
from odoo.exceptions import UserError
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PurchasePaymentRequest(models.Model):
    _name = "purchase.payment.request"
    _description = "Purchase Payment Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Payment Request",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )
    date = fields.Date(
        string="Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    date_from = fields.Date(string="Report From", tracking=True)
    date_to = fields.Date(string="Report To", tracking=True)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Prepared By",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    approver_id = fields.Many2one(
        "res.users",
        string="General Manager",
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("finance_review", "Finance Review"),
            ("gm_approval", "GM Approval"),
            ("revision", "Need Revision"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )

    line_ids = fields.One2many(
        "purchase.payment.request.line",
        "request_id",
        string="Purchase Orders",
        copy=False,
    )

    total_order = fields.Monetary(
        string="Total Purchase Orders",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    total_advance = fields.Monetary(
        string="Total Advance",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    po_count = fields.Integer(
        string="Purchase Orders",
        compute="_compute_totals",
        store=True,
    )
    effective_advance_percentage = fields.Float(
        string="Effective Advance %",
        compute="_compute_totals",
        store=True,
        digits=(16, 2),
    )

    rejection_reason = fields.Text(string="Rejection Reason", tracking=True)
    review_note = fields.Text(string="Review Note", tracking=True)

    approved_by = fields.Many2one(
        "res.users",
        string="Approved By",
        readonly=True,
        tracking=True,
    )
    approved_date = fields.Datetime(
        string="Approved Date",
        readonly=True,
        tracking=True,
    )
    rejected_by = fields.Many2one(
        "res.users",
        string="Rejected By",
        readonly=True,
        tracking=True,
    )
    rejected_date = fields.Datetime(
        string="Rejected Date",
        readonly=True,
        tracking=True,
    )

    @api.depends(
        "line_ids.amount_total",
        "line_ids.advance_amount",
        "line_ids.purchase_order_id",
    )
    def _compute_totals(self):
        for rec in self:
            total_order = sum(rec.line_ids.mapped("amount_total"))
            total_advance = sum(rec.line_ids.mapped("advance_amount"))
            rec.total_order = total_order
            rec.total_advance = total_advance
            rec.po_count = len(rec.line_ids)
            rec.effective_advance_percentage = (
                total_advance / total_order * 100.0
                if total_order else 0.0
            )

    @api.model
    def create(self, vals):
        if vals.get("name", "New") == "New":
            vals["name"] = (
                self.env["ir.sequence"].next_by_code(
                    "purchase.payment.request"
                ) or "New"
            )

        record = super(PurchasePaymentRequest, self).create(vals)
        record._collect_eligible_purchase_orders()
        return record

    def _get_used_po_ids(self, purchase_orders):
        if not purchase_orders:
            return set()

        lines = self.env["purchase.payment.request.line"].search([
            ("purchase_order_id", "in", purchase_orders.ids),
            ("request_id.state", "not in", ["draft", "rejected"]),
        ])

        return set(lines.mapped("purchase_order_id").ids)

    def _collect_eligible_purchase_orders(self):
        PurchaseOrder = self.env["purchase.order"]
        PaymentRequestLine = self.env["purchase.payment.request.line"]

        for request in self:
            if request.state != "draft":
                continue

            domain = [
                ("state", "=", "purchase"),
                ("advance_percentage", ">", 0),
                ("company_id", "=", request.company_id.id),
            ]

            if request.date_from:
                domain.append(
                    ("date_approve", ">=", fields.Datetime.to_datetime(request.date_from))
                )

            if request.date_to:
                date_to = fields.Datetime.to_datetime(request.date_to)
                date_to = date_to.replace(
                    hour=23, minute=59, second=59
                )
                domain.append(("date_approve", "<=", date_to))

            purchase_orders = PurchaseOrder.search(
                domain,
                order="date_approve asc, id asc",
            )

            if not purchase_orders:
                continue

            used_po_ids = request._get_used_po_ids(purchase_orders)
            purchase_orders = purchase_orders.filtered(
                lambda po: po.id not in used_po_ids
            )

            # Avoid duplicate lines inside the current request.
            existing_po_ids = set(
                request.line_ids.mapped("purchase_order_id").ids
            )
            purchase_orders = purchase_orders.filtered(
                lambda po: po.id not in existing_po_ids
            )

            if not purchase_orders:
                continue

            sequence = max(request.line_ids.mapped("sequence") or [0]) + 10

            for purchase_order in purchase_orders:
                PaymentRequestLine.create({
                    "request_id": request.id,
                    "purchase_order_id": purchase_order.id,
                    "sequence": sequence,
                })
                sequence += 10

            request.message_post(
                body=_(
                    "%s Purchase Order(s) were automatically collected "
                    "based on the Payment Request criteria."
                ) % len(purchase_orders)
            )

        return True

    def action_refresh_purchase_orders(self):
        for request in self:
            if request.state != "draft":
                raise UserError(_(
                    "Purchase Orders can only be refreshed while "
                    "the Payment Request is in Draft."
                ))
            request._collect_eligible_purchase_orders()
        return True

    def _check_lines(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_(
                    "No eligible Purchase Orders were found."
                ))

            for line in rec.line_ids:
                po = line.purchase_order_id
                if po.state != "purchase":
                    raise ValidationError(_(
                        "Purchase Order %s is no longer confirmed."
                    ) % po.name)

                if po.advance_percentage <= 0:
                    raise ValidationError(_(
                        "Purchase Order %s no longer has a valid "
                        "Advance Percentage."
                    ) % po.name)

    def action_submit(self):
        for rec in self:
            if rec.state not in ("draft", "revision"):
                raise UserError(_(
                    "Only Draft or Need Revision requests can be submitted."
                ))

            if rec.state == "draft":
                rec._collect_eligible_purchase_orders()

            rec._check_lines()
            rec.write({"state": "submitted"})
            rec.message_post(body=_(
                "Payment Request submitted for review."
            ))

            if rec.approver_id:
                activity_type = self.env.ref(
                    "purchase_payment_request.mail_activity_type_payment_approval",
                    raise_if_not_found=False,
                )
                if activity_type:
                    rec._schedule_activity(
                        activity_type,
                        rec.approver_id,
                    )
        return True

    def action_finance_review(self):
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_(
                    "Only Submitted requests can be moved to Finance Review."
                ))
            rec._check_lines()
            rec.write({"state": "finance_review"})
            rec.message_post(body=_("Finance review completed."))
        return True

    def _send_whatsapp_template(self, phone, template_name, variables=None):
        """Send an approved WhatsApp Cloud API template."""

        self.ensure_one()

        if not phone:
            _logger.warning(
                "WhatsApp not sent: missing phone for request %s",
                self.display_name,
            )
            return False

        params = self.env["ir.config_parameter"].sudo()

        access_token = params.get_param(
            "purchase_payment_request.whatsapp_access_token"
        )
        phone_number_id = params.get_param(
            "purchase_payment_request.whatsapp_phone_number_id"
        )
        api_version = params.get_param(
            "purchase_payment_request.whatsapp_api_version",
            "v22.0",
        )

        if not access_token or not phone_number_id:
            _logger.warning(
                "WhatsApp API is not configured."
            )
            return False

        url = (
                "https://graph.facebook.com/%s/%s/messages"
                % (api_version, phone_number_id)
        )

        components = []

        if variables:
            components.append({
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": str(value),
                    }
                    for value in variables
                ],
            })

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": "ar",
                },
                "components": components,
            },
        }

        headers = {
            "Authorization": "Bearer %s" % access_token,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=15,
            )

            if response.ok:
                _logger.info(
                    "WhatsApp sent successfully for %s",
                    self.display_name,
                )
                return True

            _logger.error(
                "WhatsApp API error: %s",
                response.text,
            )

        except requests.RequestException:
            _logger.exception(
                "WhatsApp connection failed for %s",
                self.display_name,
            )

        return False
    def action_send_to_gm(self):
        for rec in self:
            if rec.state != "finance_review":
                raise UserError(_(
                    "Only requests in Finance Review can be sent "
                    "to the General Manager."
                ))

            if not rec.approver_id:
                raise UserError(_(
                    "Please select the General Manager."
                ))

            rec.write({"state": "gm_approval"})
            rec.message_post(body=_(
                "Payment Request sent to %s for approval."
            ) % rec.approver_id.name)

            activity_type = self.env.ref(
                "purchase_payment_request.mail_activity_type_payment_approval",
                raise_if_not_found=False,
            )
            if activity_type:
                rec._schedule_activity(
                    activity_type,
                    rec.approver_id,
                )
            # WhatsApp notification to General Manager
            gm_partner = rec.approver_id.partner_id
            gm_phone = gm_partner.mobile or gm_partner.phone

            sent = rec._send_whatsapp_template(
                phone=gm_phone,
                template_name="payment_request_gm_approval",
                variables=[
                    rec.display_name,
                    rec.create_uid.name,
                ],
            )

            if sent:
                rec.message_post(
                    body=_("WhatsApp notification sent to the General Manager.")
                )
        return True

    def _schedule_activity(self, activity_type, user):
        if not user:
            return

        self.activity_schedule(
            activity_type_id=activity_type.id,
            user_id=user.id,
            summary=_("Payment Request requires your action"),
        )

    def action_approve(self):
        for rec in self:
            if rec.state != "gm_approval":
                raise UserError(_(
                    "Only requests waiting for GM Approval can be approved."
                ))

            rec.write({
                "state": "approved",
                "approved_by": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })

            rec.message_post(
                body=_("Approved by %s.") % self.env.user.name
            )

            # Notify the request preparer through WhatsApp
            partner = rec.user_id.partner_id
            phone = partner.mobile or partner.phone

            sent = rec._send_whatsapp_template(
                phone=phone,
                template_name="payment_request_approved",
                variables=[
                    rec.name,
                    self.env.user.name,
                ],
            )

            if sent:
                rec.message_post(
                    body=_(
                        "WhatsApp approval notification sent to the requester."
                    )
                )

        return True

    def action_request_revision(self):
        for rec in self:
            if rec.state not in (
                "submitted",
                "finance_review",
                "gm_approval",
            ):
                raise UserError(_(
                    "Revision cannot be requested from the current state."
                ))

            rec.write({"state": "revision"})
            rec.message_post(body=_(
                "Revision requested by %s. %s"
            ) % (
                self.env.user.name,
                rec.review_note or "",
            ))

        return True

    def action_reject(self):
        self.ensure_one()

        if self.state in ("approved", "rejected"):
            raise UserError(_(
                "This Payment Request can no longer be rejected."
            ))

        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Payment Request"),
            "res_model": "purchase.payment.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_id": self.id,
            },
        }

    def action_open_purchase_orders(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Orders"),
            "res_model": "purchase.order",
            "view_mode": "tree,form",
            "domain": [
                (
                    "id",
                    "in",
                    self.line_ids.mapped("purchase_order_id").ids,
                )
            ],
        }


class PurchasePaymentRequestLine(models.Model):
    _name = "purchase.payment.request.line"
    _description = "Purchase Payment Request Line"
    _order = "sequence, id"

    request_id = fields.Many2one(
        "purchase.payment.request",
        string="Payment Request",
        required=True,
        ondelete="cascade",
        index=True,
    )

    sequence = fields.Integer(
        string="Sequence",
        default=10,
    )

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="Purchase Order",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )

    date_approve = fields.Datetime(
        related="purchase_order_id.date_approve",
        string="Approval Date",
        store=True,
        readonly=True,
    )

    partner_id = fields.Many2one(
        "res.partner",
        related="purchase_order_id.partner_id",
        string="Vendor",
        store=True,
        readonly=True,
    )

    partner_ref = fields.Char(
        related="purchase_order_id.partner_ref",
        string="Vendor Reference",
        store=True,
        readonly=True,
    )

    # Odoo 14 project/analytic customization:
    # Purchase Order must contain Analytic_id with comodel account.analytic.account.
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        related="purchase_order_id.picking_type_id.warehouse_id",
        store=True,
    )

    amount_total = fields.Monetary(
        related="purchase_order_id.amount_total",
        string="Purchase Order Amount",
        store=True,
        currency_field="currency_id",
        readonly=True,
    )

    advance_percentage = fields.Float(
        related="purchase_order_id.advance_percentage",
        string="Advance %",
        store=True,
        digits=(16, 2),
        readonly=True,
    )

    advance_amount = fields.Monetary(
        string="Advance Amount",
        compute="_compute_advance",
        store=True,
        currency_field="currency_id",
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="purchase_order_id.currency_id",
        string="Currency",
        store=True,
        readonly=True,
    )

    @api.depends("amount_total", "advance_percentage")
    def _compute_advance(self):
        for line in self:
            line.advance_amount = (
                line.amount_total
                * line.advance_percentage
                / 100.0
            )

    def unlink(self):
        raise UserError(_(
            "Payment Request lines cannot be deleted manually. "
            "They are managed automatically from Purchase Orders."
        ))


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    advance_percentage = fields.Float(
        string='Advance Percentage',
        digits=(16, 2),
        default=0.0,
    )

    payment_request_ids = fields.One2many(
        "purchase.payment.request.line",
        "purchase_order_id",
        string="Payment Requests",
        readonly=True,
    )

    payment_request_count = fields.Integer(
        string="Payment Requests",
        compute="_compute_payment_request_count",
    )

    def _compute_payment_request_count(self):
        for order in self:
            order.payment_request_count = len(
                order.payment_request_ids
            )

    def action_open_payment_requests(self):
        self.ensure_one()

        requests = self.payment_request_ids.mapped("request_id")

        if not requests:
            raise UserError(_(
                "This Purchase Order is not included in any Payment Request."
            ))

        if len(requests) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Payment Request"),
                "res_model": "purchase.payment.request",
                "view_mode": "form",
                "res_id": requests.id,
                "target": "current",
            }

        return {
            "type": "ir.actions.act_window",
            "name": _("Payment Requests"),
            "res_model": "purchase.payment.request",
            "view_mode": "tree,form",
            "domain": [("id", "in", requests.ids)],
        }
