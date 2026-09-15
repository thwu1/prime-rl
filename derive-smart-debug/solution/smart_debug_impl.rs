
use proc_macro::TokenStream;
use proc_macro2::TokenStream as TokenStream2;
use quote::{format_ident, quote};
use std::collections::HashSet;
use syn::{
    parse_macro_input, Data, DeriveInput, Field, Fields, GenericParam, Index, LitStr, Type,
    TypePath, Variant, WhereClause, WherePredicate,
};

#[proc_macro_derive(SmartDebug, attributes(debug))]
pub fn smart_debug_derive(input: TokenStream) -> TokenStream {
    let input = parse_macro_input!(input as DeriveInput);
    match impl_smart_debug(&input) {
        Ok(tokens) => tokens.into(),
        Err(err) => err.to_compile_error().into(),
    }
}

// ---------- attribute parsing ----------

#[derive(Default)]
struct FieldAttrs {
    skip: bool,
    fmt: Option<LitStr>,
    rename: Option<LitStr>,
    with_fn: Option<LitStr>,
}

fn parse_field_attrs(field: &Field) -> syn::Result<FieldAttrs> {
    let mut attrs = FieldAttrs::default();
    for attr in &field.attrs {
        if attr.path().is_ident("debug") {
            attr.parse_nested_meta(|meta| {
                if meta.path.is_ident("skip") {
                    attrs.skip = true;
                    Ok(())
                } else if meta.path.is_ident("fmt") {
                    let value = meta.value()?;
                    attrs.fmt = Some(value.parse()?);
                    Ok(())
                } else if meta.path.is_ident("rename") {
                    let value = meta.value()?;
                    attrs.rename = Some(value.parse()?);
                    Ok(())
                } else if meta.path.is_ident("with") {
                    let value = meta.value()?;
                    attrs.with_fn = Some(value.parse()?);
                    Ok(())
                } else {
                    Err(meta.error("unknown SmartDebug attribute"))
                }
            })?;
        }
    }
    Ok(attrs)
}

// ---------- PhantomData detection ----------

fn is_phantom_data(ty: &Type) -> bool {
    if let Type::Path(TypePath { qself: None, path }) = ty {
        path.segments
            .last()
            .map(|seg| seg.ident == "PhantomData")
            .unwrap_or(false)
    } else {
        false
    }
}

// ---------- type parameter usage analysis ----------

fn type_contains_param(ty: &Type, param_name: &str) -> bool {
    match ty {
        Type::Path(TypePath { qself, path }) => {
            if let Some(qs) = qself {
                if type_contains_param(&qs.ty, param_name) {
                    return true;
                }
            }
            if path.is_ident(param_name) {
                return true;
            }
            for segment in &path.segments {
                match &segment.arguments {
                    syn::PathArguments::AngleBracketed(args) => {
                        for arg in &args.args {
                            if let syn::GenericArgument::Type(inner_ty) = arg {
                                if type_contains_param(inner_ty, param_name) {
                                    return true;
                                }
                            }
                        }
                    }
                    syn::PathArguments::Parenthesized(args) => {
                        for input_ty in &args.inputs {
                            if type_contains_param(input_ty, param_name) {
                                return true;
                            }
                        }
                        if let syn::ReturnType::Type(_, ret_ty) = &args.output {
                            if type_contains_param(ret_ty, param_name) {
                                return true;
                            }
                        }
                    }
                    syn::PathArguments::None => {}
                }
            }
            false
        }
        Type::Reference(r) => type_contains_param(&r.elem, param_name),
        Type::Tuple(t) => t.elems.iter().any(|e| type_contains_param(e, param_name)),
        Type::Array(a) => type_contains_param(&a.elem, param_name),
        Type::Slice(s) => type_contains_param(&s.elem, param_name),
        Type::Paren(p) => type_contains_param(&p.elem, param_name),
        Type::Group(g) => type_contains_param(&g.elem, param_name),
        Type::BareFn(f) => {
            f.inputs
                .iter()
                .any(|arg| type_contains_param(&arg.ty, param_name))
                || matches!(&f.output, syn::ReturnType::Type(_, ty) if type_contains_param(ty, param_name))
        }
        _ => false,
    }
}

/// Determine which type parameters need `Debug` bounds based on field usage.
fn collect_debug_bounds<'a>(
    input: &DeriveInput,
    fields: impl Iterator<Item = &'a Field>,
) -> syn::Result<Vec<WherePredicate>> {
    let type_params: Vec<String> = input
        .generics
        .params
        .iter()
        .filter_map(|p| {
            if let GenericParam::Type(tp) = p {
                Some(tp.ident.to_string())
            } else {
                None
            }
        })
        .collect();

    if type_params.is_empty() {
        return Ok(Vec::new());
    }

    let mut needs_bound: HashSet<String> = HashSet::new();

    for field in fields {
        let attrs = parse_field_attrs(field)?;
        if attrs.skip || is_phantom_data(&field.ty) {
            continue;
        }
        for param_name in &type_params {
            if type_contains_param(&field.ty, param_name) {
                needs_bound.insert(param_name.clone());
            }
        }
    }

    let mut bounds: Vec<WherePredicate> = Vec::new();
    // Maintain declaration order for deterministic output
    for param_name in &type_params {
        if needs_bound.contains(param_name) {
            let ident = format_ident!("{}", param_name);
            bounds.push(syn::parse_quote!(#ident: std::fmt::Debug));
        }
    }

    Ok(bounds)
}

// ---------- where-clause merging ----------

fn merge_where_clause(
    existing: Option<&WhereClause>,
    extra: &[WherePredicate],
) -> Option<WhereClause> {
    if extra.is_empty() {
        return existing.cloned();
    }

    let mut clause = existing.cloned().unwrap_or_else(|| WhereClause {
        where_token: Default::default(),
        predicates: Default::default(),
    });

    for pred in extra {
        clause.predicates.push(pred.clone());
    }

    Some(clause)
}

// ---------- field formatting code generation ----------

/// Generate a `.field("name", &value)` call for a named field in debug_struct.
fn gen_named_field(
    field: &Field,
    field_access: TokenStream2,
) -> syn::Result<Option<TokenStream2>> {
    let attrs = parse_field_attrs(field)?;

    if attrs.skip || is_phantom_data(&field.ty) {
        return Ok(None);
    }

    let field_name = field.ident.as_ref().unwrap();
    let display_name = if let Some(ref rename) = attrs.rename {
        rename.value()
    } else {
        field_name.to_string()
    };

    if let Some(ref fmt_str) = attrs.fmt {
        Ok(Some(quote! {
            .field(#display_name, &format_args!(#fmt_str, #field_access))
        }))
    } else if let Some(ref with_fn) = attrs.with_fn {
        let fn_path: syn::Path = syn::parse_str(&with_fn.value())?;
        Ok(Some(quote! {
            .field(#display_name, &{
                struct __SmartDebugWith<__F: Fn(&mut std::fmt::Formatter<'_>) -> std::fmt::Result>(__F);
                impl<__F: Fn(&mut std::fmt::Formatter<'_>) -> std::fmt::Result> std::fmt::Debug for __SmartDebugWith<__F> {
                    fn fmt(&self, __f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                        (self.0)(__f)
                    }
                }
                __SmartDebugWith(|__f: &mut std::fmt::Formatter<'_>| #fn_path(#field_access, __f))
            })
        }))
    } else {
        Ok(Some(quote! {
            .field(#display_name, #field_access)
        }))
    }
}

/// Generate a `.field(&value)` call for an unnamed field in debug_tuple.
fn gen_unnamed_field(
    field: &Field,
    field_access: TokenStream2,
) -> syn::Result<Option<TokenStream2>> {
    let attrs = parse_field_attrs(field)?;

    if attrs.skip {
        return Ok(None);
    }

    if let Some(ref fmt_str) = attrs.fmt {
        Ok(Some(quote! {
            .field(&format_args!(#fmt_str, #field_access))
        }))
    } else if let Some(ref with_fn) = attrs.with_fn {
        let fn_path: syn::Path = syn::parse_str(&with_fn.value())?;
        Ok(Some(quote! {
            .field(&{
                struct __SmartDebugWith<__F: Fn(&mut std::fmt::Formatter<'_>) -> std::fmt::Result>(__F);
                impl<__F: Fn(&mut std::fmt::Formatter<'_>) -> std::fmt::Result> std::fmt::Debug for __SmartDebugWith<__F> {
                    fn fmt(&self, __f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                        (self.0)(__f)
                    }
                }
                __SmartDebugWith(|__f: &mut std::fmt::Formatter<'_>| #fn_path(#field_access, __f))
            })
        }))
    } else {
        Ok(Some(quote! {
            .field(#field_access)
        }))
    }
}

// ---------- struct impl ----------

fn impl_struct_debug(input: &DeriveInput) -> syn::Result<TokenStream2> {
    let name = &input.ident;
    let name_str = name.to_string();

    let data = match &input.data {
        Data::Struct(data) => data,
        _ => unreachable!(),
    };

    let extra_bounds = collect_debug_bounds(input, data.fields.iter())?;

    let (impl_generics, ty_generics, where_clause) = input.generics.split_for_impl();
    let where_clause = merge_where_clause(where_clause, &extra_bounds);

    let body = match &data.fields {
        Fields::Named(fields) => {
            let field_entries: Vec<TokenStream2> = fields
                .named
                .iter()
                .filter_map(|f| {
                    let field_name = f.ident.as_ref().unwrap();
                    let access = quote!(&self.#field_name);
                    gen_named_field(f, access).transpose()
                })
                .collect::<syn::Result<Vec<_>>>()?;

            quote! {
                f.debug_struct(#name_str)
                    #(#field_entries)*
                    .finish()
            }
        }
        Fields::Unnamed(fields) => {
            let field_entries: Vec<TokenStream2> = fields
                .unnamed
                .iter()
                .enumerate()
                .filter_map(|(i, f)| {
                    let idx = Index::from(i);
                    let access = quote!(&self.#idx);
                    gen_unnamed_field(f, access).transpose()
                })
                .collect::<syn::Result<Vec<_>>>()?;

            quote! {
                f.debug_tuple(#name_str)
                    #(#field_entries)*
                    .finish()
            }
        }
        Fields::Unit => {
            quote! {
                f.write_str(#name_str)
            }
        }
    };

    Ok(quote! {
        impl #impl_generics std::fmt::Debug for #name #ty_generics #where_clause {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                #body
            }
        }
    })
}

// ---------- enum impl ----------

fn gen_enum_arm(enum_name: &syn::Ident, variant: &Variant) -> syn::Result<TokenStream2> {
    let variant_name = &variant.ident;
    let variant_str = variant_name.to_string();

    match &variant.fields {
        Fields::Unit => Ok(quote! {
            #enum_name::#variant_name => f.write_str(#variant_str),
        }),
        Fields::Named(fields) => {
            let field_names: Vec<_> = fields
                .named
                .iter()
                .map(|f| f.ident.as_ref().unwrap())
                .collect();
            let bindings: Vec<TokenStream2> =
                field_names.iter().map(|name| quote!(ref #name)).collect();

            let field_entries: Vec<TokenStream2> = fields
                .named
                .iter()
                .filter_map(|f| {
                    let field_name = f.ident.as_ref().unwrap();
                    let access = quote!(#field_name);
                    gen_named_field(f, access).transpose()
                })
                .collect::<syn::Result<Vec<_>>>()?;

            Ok(quote! {
                #enum_name::#variant_name { #(#field_names: #bindings),* } => {
                    f.debug_struct(#variant_str)
                        #(#field_entries)*
                        .finish()
                },
            })
        }
        Fields::Unnamed(fields) => {
            let binding_names: Vec<syn::Ident> = (0..fields.unnamed.len())
                .map(|i| format_ident!("__v{}", i))
                .collect();

            let field_entries: Vec<TokenStream2> = fields
                .unnamed
                .iter()
                .enumerate()
                .filter_map(|(i, f)| {
                    let binding = &binding_names[i];
                    let access = quote!(#binding);
                    gen_unnamed_field(f, access).transpose()
                })
                .collect::<syn::Result<Vec<_>>>()?;

            Ok(quote! {
                #enum_name::#variant_name(#(ref #binding_names),*) => {
                    f.debug_tuple(#variant_str)
                        #(#field_entries)*
                        .finish()
                },
            })
        }
    }
}

fn impl_enum_debug(input: &DeriveInput) -> syn::Result<TokenStream2> {
    let name = &input.ident;

    let data = match &input.data {
        Data::Enum(data) => data,
        _ => unreachable!(),
    };

    // Collect bounds from ALL variant fields
    let all_fields: Vec<&Field> = data.variants.iter().flat_map(|v| v.fields.iter()).collect();
    let extra_bounds = collect_debug_bounds(input, all_fields.into_iter())?;

    let (impl_generics, ty_generics, where_clause) = input.generics.split_for_impl();
    let where_clause = merge_where_clause(where_clause, &extra_bounds);

    let arms: Vec<TokenStream2> = data
        .variants
        .iter()
        .map(|variant| gen_enum_arm(name, variant))
        .collect::<syn::Result<Vec<_>>>()?;

    Ok(quote! {
        impl #impl_generics std::fmt::Debug for #name #ty_generics #where_clause {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                match self {
                    #(#arms)*
                }
            }
        }
    })
}

// ---------- top-level dispatch ----------

fn impl_smart_debug(input: &DeriveInput) -> syn::Result<TokenStream2> {
    match &input.data {
        Data::Struct(_) => impl_struct_debug(input),
        Data::Enum(_) => impl_enum_debug(input),
        Data::Union(_) => Err(syn::Error::new_spanned(
            &input.ident,
            "SmartDebug does not support unions",
        )),
    }
}
