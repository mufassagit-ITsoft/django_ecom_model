from django.shortcuts import render
from . models import ShippingAddress, Order, OrderItem
from cart.cart import Cart
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from store.models import Product
from decimal import Decimal


def checkout(request):
    # Users with accounts -- Pre-fill the form
    if request.user.is_authenticated:
        try:
            # Authenticated users WITH shipping information 
            shipping_address = ShippingAddress.objects.get(user=request.user.id)
            context = {'shipping': shipping_address}
            return render(request, 'payment/checkout.html', context=context)
        except:
            # Authenticated users with NO shipping information
            return render(request, 'payment/checkout.html')
    else:
        # Guest users
        return render(request, 'payment/checkout.html')


def complete_order(request):
    if request.POST.get('action') == 'post':
        name = request.POST.get('name')
        email = request.POST.get('email')
        address1 = request.POST.get('address1')
        address2 = request.POST.get('address2')
        city = request.POST.get('city')
        state = request.POST.get('state')
        zipcode = request.POST.get('zipcode')

        # All-in-one shipping address
        shipping_address = (address1 + "\n" + address2 + "\n" +
        city + "\n" + state + "\n" + zipcode)

        # Shopping cart information 
        cart = Cart(request)

        # Get the total price of items
        total_cost = cart.get_total()

        # Initialize product list and validation
        product_list = []
        insufficient_stock = []

        # STEP 1: Validate stock availability for all items BEFORE processing
        for item in cart:
            product = item['product']
            quantity = item['qty']
            
            if not product.can_fulfill_order(quantity):
                insufficient_stock.append({
                    'product': product.title,
                    'requested': quantity,
                    'available': product.quantity_available
                })
        
        # If any product has insufficient stock, return error
        if insufficient_stock:
            error_message = "Unable to complete order. Insufficient stock for: "
            error_details = ", ".join([
                f"{item['product']} (requested: {item['requested']}, available: {item['available']})"
                for item in insufficient_stock
            ])
            
            response = JsonResponse({
                'success': False,
                'error': error_message + error_details
            })
            return response

        # STEP 2: Create order (stock is available for all items)
        if request.user.is_authenticated:
            order = Order.objects.create(
                full_name=name, 
                email=email, 
                shipping_address=shipping_address,
                amount_paid=total_cost, 
                user=request.user
            )
            order_id = order.pk

            # Create order items and update product inventory
            for item in cart:
                product = item['product']
                quantity = item['qty']
                price = item['price']
                
                # Create order item
                OrderItem.objects.create(
                    order_id=order_id, 
                    product=product, 
                    quantity=quantity,
                    price=price, 
                    user=request.user
                )
                
                # Update product inventory and sales tracking
                total_item_price = Decimal(str(price)) * quantity
                product.process_sale(quantity, total_item_price)
                product_list.append(product.title)

        else:
            # Guest users
            order = Order.objects.create(
                full_name=name, 
                email=email, 
                shipping_address=shipping_address,
                amount_paid=total_cost
            )
            order_id = order.pk

            # Create order items and update product inventory
            for item in cart:
                product = item['product']
                quantity = item['qty']
                price = item['price']
                
                # Create order item
                OrderItem.objects.create(
                    order_id=order_id, 
                    product=product, 
                    quantity=quantity,
                    price=price
                )
                
                # Update product inventory and sales tracking
                total_item_price = Decimal(str(price)) * quantity
                product.process_sale(quantity, total_item_price)
                product_list.append(product.title)

        # Send confirmation email
        try:
            send_mail(
                'Order received', 
                'Hi! ' + '\n\n' + 'Thank you for placing your order' + '\n\n' +
                'Please see your order below: ' + '\n\n' + str(product_list) + '\n\n' + 
                'Total paid: $' + str(total_cost), 
                settings.EMAIL_HOST_USER, 
                [email], 
                fail_silently=False
            )
        except Exception as e:
            # Log email error but don't fail the order
            print(f"Email sending failed: {e}")

        order_success = True
        response = JsonResponse({'success': order_success})
        return response


def payment_success(request):
    # Clear shopping cart
    for key in list(request.session.keys()):
        if key == 'session_key':
            del request.session[key]

    return render(request, 'payment/payment-success.html')


def payment_failed(request):
    return render(request, 'payment/payment-failed.html')