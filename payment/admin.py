from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from .models import ShippingAddress, Order, OrderItem, RefundRequest, RefundItem

admin.site.register(ShippingAddress)
admin.site.register(Order)
admin.site.register(OrderItem)

# Refund Admin

class RefundItemInline(admin.TabularInline):
    model = RefundItem
    extra = 0
    readonly_fields = ['order_item', 'quantity_to_refund', 'refund_amount']
    fields = ['order_item', 'quantity_to_refund', 'refund_amount', 
              'condition_acceptable', 'condition_notes', 'restocked']
    
    def has_add_permission(self, request, obj=None):
        return False  # Items are added when refund request is created


@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'order_link',
        'customer_info',
        'refund_amount_display',
        'status_badge',
        'reason',
        'created_at',
        'action_buttons'
    ]
    
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['order__id', 'customer_email', 'customer_name', 'user__username']
    date_hierarchy = 'created_at'
    
    readonly_fields = [
        'order',
        'user',
        'customer_email',
        'customer_name',
        'refund_amount',
        'rewards_used',
        'created_at',
        'updated_at',
        'product_received_at',
        'refund_completed_at'
    ]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order', 'user', 'customer_name', 'customer_email')
        }),
        ('Refund Details', {
            'fields': ('status', 'reason', 'reason_details', 'refund_amount', 'rewards_used')
        }),
        ('Return Tracking', {
            'fields': ('tracking_number', 'product_received_at')
        }),
        ('PayPal Refund', {
            'fields': ('paypal_refund_id', 'refund_completed_at')
        }),
        ('Admin Management', {
            'fields': ('admin_notes', 'rejection_reason')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [RefundItemInline]
    
    actions = [
        'mark_product_received',
        'process_paypal_refund',
        'complete_refund',
        'reject_refund'
    ]
    
    def order_link(self, obj):
        """Clickable link to order"""
        url = reverse('admin:payment_order_change', args=[obj.order.id])
        return format_html('<a href="{}">Order #{}</a>', url, obj.order.id)
    order_link.short_description = 'Order'
    
    def customer_info(self, obj):
        """Display customer information"""
        if obj.user:
            return format_html(
                '<strong>{}</strong><br><small>{}</small>',
                obj.user.username,
                obj.customer_email
            )
        return format_html(
            '<strong>Guest</strong><br><small>{}</small>',
            obj.customer_email
        )
    customer_info.short_description = 'Customer'
    
    def refund_amount_display(self, obj):
        """Display refund amount with rewards info"""
        html = format_html('<strong>${:.2f}</strong>', obj.refund_amount)
        if obj.rewards_used > 0:
            html += format_html(
                '<br><small style="color: #dc3545;">Rewards: ${:.2f}</small>',
                obj.rewards_used
            )
        return html
    refund_amount_display.short_description = 'Refund Amount'
    
    def status_badge(self, obj):
        """Display status as colored badge"""
        return format_html(
            '<span style="background-color: {}; color: white; padding: 5px 10px; border-radius: 5px; font-weight: bold;">{}</span>',
            self._get_status_color(obj.status),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def _get_status_color(self, status):
        """Get color for status badge"""
        colors = {
            'PENDING_RETURN': '#ffc107',  # Yellow
            'PRODUCT_RECEIVED': '#17a2b8',  # Blue
            'PROCESSING_REFUND': '#007bff',  # Dark blue
            'COMPLETED': '#28a745',  # Green
            'REJECTED': '#dc3545',  # Red
            'CANCELLED': '#6c757d',  # Gray
        }
        return colors.get(status, '#6c757d')
    
    def action_buttons(self, obj):
        """Display quick action buttons"""
        buttons = []
        
        if obj.status == 'PENDING_RETURN':
            buttons.append(
                '<span style="background-color: #17a2b8; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">Waiting for Return</span>'
            )
        
        if obj.status == 'PRODUCT_RECEIVED':
            buttons.append(
                '<span style="background-color: #28a745; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">Ready to Process</span>'
            )
        
        return format_html(' '.join(buttons)) if buttons else '-'
    action_buttons.short_description = 'Quick Actions'
    
    # ═══════════════════════════════════════════════════════════════════════
    # ADMIN ACTIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    def mark_product_received(self, request, queryset):
        """Mark selected refunds as product received"""
        from .models import restock_refunded_items
        
        updated = 0
        for refund in queryset.filter(status='PENDING_RETURN'):
            refund.status = 'PRODUCT_RECEIVED'
            refund.product_received_at = timezone.now()
            refund.save()
            
            # Restock items if condition acceptable
            try:
                restock_refunded_items(refund)
            except Exception as e:
                self.message_user(
                    request,
                    f'Error restocking items for refund #{refund.id}: {e}',
                    level=messages.ERROR
                )
            
            updated += 1
        
        self.message_user(
            request,
            f'{updated} refund(s) marked as product received and items restocked.',
            level=messages.SUCCESS
        )
    mark_product_received.short_description = '✓ Mark product received & restock'
    
    def process_paypal_refund(self, request, queryset):
        """Process PayPal refund (manual - admin must do this in PayPal)"""
        updated = 0
        for refund in queryset.filter(status='PRODUCT_RECEIVED'):
            refund.status = 'PROCESSING_REFUND'
            refund.save()
            updated += 1
        
        self.message_user(
            request,
            f'{updated} refund(s) marked as processing. Please process refunds in PayPal dashboard and enter transaction IDs.',
            level=messages.WARNING
        )
    process_paypal_refund.short_description = '→ Mark as processing PayPal refund'
    
    def complete_refund(self, request, queryset):
        """Complete the refund process"""
        from .models import process_rewards_refund
        
        updated = 0
        for refund in queryset.filter(status='PROCESSING_REFUND'):
            # Process rewards adjustments for registered users
            if refund.user:
                try:
                    process_rewards_refund(refund)
                except Exception as e:
                    self.message_user(
                        request,
                        f'Error processing rewards for refund #{refund.id}: {e}',
                        level=messages.ERROR
                    )
                    continue
            
            refund.status = 'COMPLETED'
            refund.refund_completed_at = timezone.now()
            refund.save()
            updated += 1
        
        self.message_user(
            request,
            f'{updated} refund(s) completed successfully. Rewards have been adjusted for registered users.',
            level=messages.SUCCESS
        )
    complete_refund.short_description = '✓ Complete refund & adjust rewards'
    
    def reject_refund(self, request, queryset):
        """Reject selected refund requests"""
        updated = queryset.exclude(status__in=['COMPLETED', 'REJECTED']).update(
            status='REJECTED'
        )
        
        self.message_user(
            request,
            f'{updated} refund(s) rejected. Please add rejection reason in admin notes.',
            level=messages.WARNING
        )
    reject_refund.short_description = '✗ Reject refund request'


@admin.register(RefundItem)
class RefundItemAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'refund_request',
        'product_name',
        'quantity_to_refund',
        'refund_amount',
        'condition_acceptable',
        'restocked'
    ]
    
    list_filter = ['condition_acceptable', 'restocked']
    search_fields = ['refund_request__id', 'order_item__product__title']
    
    readonly_fields = ['refund_request', 'order_item', 'quantity_to_refund', 'refund_amount']
    
    def product_name(self, obj):
        """Display product name"""
        return obj.order_item.product.title
    product_name.short_description = 'Product'

