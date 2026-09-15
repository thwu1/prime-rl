//
// Reference CLI tool for Uiua's geometric algebra conventions.
// Compiled from ga.rs during image build.

include!("/app/reference/ga.rs");

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("ga_tool — reference CLI for Uiua GA conventions");
        eprintln!();
        eprintln!("Usage:");
        eprintln!("  ga_tool mask_tables <dims>");
        eprintln!("  ga_tool metric <index> <p> <q> <r>");
        eprintln!("  ga_tool blade_grades <dims>");
        eprintln!("  ga_tool grade_ranges <dims>");
        std::process::exit(1);
    }
    match args[1].as_str() {
        "mask_tables" => {
            let dims: u8 = args[2].parse().expect("dims: u8");
            let n = 1usize << dims;
            let (mt, imt) = mask_tables(dims);
            print!("mask_table: [");
            for i in 0..n {
                if i > 0 { print!(", "); }
                print!("{}", mt[i]);
            }
            println!("]");
            print!("inv_mask_table: [");
            for i in 0..n {
                if i > 0 { print!(", "); }
                print!("{}", imt[i]);
            }
            println!("]");
        }
        "metric" => {
            let idx: u8 = args[2].parse().expect("index: u8");
            let p: u8 = args[3].parse().expect("p: u8");
            let q: u8 = args[4].parse().expect("q: u8");
            let r: u8 = args[5].parse().expect("r: u8");
            println!("{}", Flavor::Cl(p, q, r).metric(idx));
        }
        "blade_grades" => {
            let dims: u8 = args[2].parse().expect("dims: u8");
            let grades: Vec<u8> = blade_grades(dims).collect();
            print!("[");
            for (i, g) in grades.iter().enumerate() {
                if i > 0 { print!(", "); }
                print!("{}", g);
            }
            println!("]");
        }
        "grade_ranges" => {
            let dims: u8 = args[2].parse().expect("dims: u8");
            for g in 0..=dims {
                println!("grade {}: {} blades", g, grade_size(dims, g));
            }
        }
        cmd => {
            eprintln!("Unknown command: {}", cmd);
            std::process::exit(1);
        }
    }
}
