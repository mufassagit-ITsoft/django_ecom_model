from django.shortcuts import render
from . models import Category, Product
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.template.loader import render_to_string
from django.http import HttpResponse


def store(request):
    all_products = Product.objects.all()
    context = {'my_products':all_products}
    return render(request, 'store/store.html', context)

def categories(request):
    all_categories = Category.objects.all()
    return {'all_categories': all_categories}

def list_category(request, category_slug=None):
    category = get_object_or_404(Category, slug=category_slug)
    products = Product.objects.filter(category=category)
    return render(request, 'store/list-category.html', {'category':category, 'products':products})

def product_info(request, product_slug):
    product = get_object_or_404(Product, slug=product_slug)
    context = {'product': product}
    return render(request, 'store/product-info.html', context)

def search_products(request):
    query = request.GET.get('q', '')
    is_ajax = request.GET.get('ajax', '') == '1'
    if query:
        # Search in product title, brand, and description
        products = Product.objects.filter(
            Q(title__icontains=query) | 
            Q(brand__icontains=query) | 
            Q(description__icontains=query)
        ).distinct()[:10]  # Limit to 10 results for AJAX
    else:
        products = Product.objects.none()
    # If this is an AJAX request, return HTML snippet for suggestions
    if is_ajax:
        html = render_to_string('store/search-suggestions.html', {'products': products, 'query': query})
        return HttpResponse(html)
    # Otherwise, return full page
    context = {
        'products': products,
        'query': query,
        'product_count': products.count()
    }
    return render(request, 'store/search-results.html', context)