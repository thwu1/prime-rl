use proc_macro::TokenStream;

/// Derive macro for generating std::fmt::Debug implementations.
///
/// Supports attributes: #[debug(skip)], #[debug(fmt = "...")],
/// #[debug(rename = "...")], #[debug(with = "path::to::fn")]
///
/// Auto-skips PhantomData fields. Only adds Debug bounds for type
/// parameters used in non-skipped, non-PhantomData fields.
#[proc_macro_derive(SmartDebug, attributes(debug))]
pub fn smart_debug_derive(input: TokenStream) -> TokenStream {
    // TODO: implement
    TokenStream::new()
}
