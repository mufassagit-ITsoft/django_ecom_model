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
        'order_id_simple',  # Changed from order_link - NO FORMAT_HTML
        'customer_info',
        'refund_amount_simple',  # Changed - SIMPLIFIED
        'status_simple',  # Changed - SIMPLIFIED
        'reason',
        'created_at',
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
    
    # SIMPLIFIED METHODS - NO FORMAT_HTML AT ALL
    
    def order_id_simple(self, obj):
        """Simple order ID - plain text, no formatting"""
        try:
            if obj and obj.order and obj.order.id:
                return f"Order #{obj.order.id}"
            return "-"
        except Exception as e:
            return f"Error: {e}"
    order_id_simple.short_description = 'Order'
    
    def customer_info(self, obj):
        """Display customer information"""
        try:
            if obj.user:
                return f"{obj.user.username} ({obj.customer_email})"
            return f"Guest ({obj.customer_email})"
        except Exception as e:
            return f"Error: {e}"
    customer_info.short_description = 'Customer'
    
    def refund_amount_simple(self, obj):
        """Simple refund amount display"""
        try:
            amount = f"${float(obj.refund_amount):.2f}"
            if obj.rewards_used > 0:
                amount += f" (Rewards: ${float(obj.rewards_used):.2f})"
            return amount
        except Exception as e:
            return f"Error: {e}"
    refund_amount_simple.short_description = 'Refund Amount'
    
    def status_simple(self, obj):
        """Simple status display"""
        try:
            return obj.get_status_display()
        except Exception as e:
            return f"Error: {e}"
    status_simple.short_description = 'Status'
    
    # ═══════════════════════════════════════════════════════════════════
    # ADMIN ACTIONS
    # ═══════════════════════════════════════════════════════════════════
    
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
        try:
            return obj.order_item.product.title
        except Exception as e:
            return f"Error: {e}"
    product_name.short_description = 'Product'
