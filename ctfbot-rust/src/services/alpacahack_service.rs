
use rusqlite::{Connection, Result};
use scraper::{ElementRef, Html, Node, Selector};

// Helper function to extract text, excluding style tags
fn extract_text_excluding_style(element: &ElementRef) -> String {
    element
        .children()
        .filter_map(|node| {
            if let Some(element) = ElementRef::wrap(node) {
                if element.value().name() == "style" {
                    None
                } else {
                    Some(element.text().collect::<String>())
                }
            } else if let Node::Text(text_node) = node.value() {
                Some(text_node.text.to_string())
            } else {
                None
            }
        })
        .collect::<String>()
}

// pub async fn get_alpacahack_info(user: &str) -> Result<Vec<AlpacaHackInfo>, reqwest::Error> {
//     let url = format!("https://alpacahack.com/api/user/{}/solves", user);
//     let info = reqwest::get(&url)
//         .await?
//         .json::<Vec<AlpacaHackInfo>>()
//         .await?;
//     Ok(info)
// }

pub async fn get_alpacahack_solves_scraped(
    user: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    let url = format!("https://alpacahack.com/users/{}", user);
    let response = reqwest::get(&url).await?.text().await?;
    let document = Html::parse_document(&response);

    let tbody_selector = Selector::parse("tbody.MuiTableBody-root").unwrap();
    let tr_selector = Selector::parse("tr").unwrap();
    let td_selector = Selector::parse("td").unwrap();
    let a_selector = Selector::parse("a").unwrap();
    let p_selector = Selector::parse("p").unwrap();

    let mut result = Vec::new();
    result.push(user.to_string());
    result.push(format!(
        "{:20}{:20}{:20}",
        "CHALLENGE", "SOLVES", "SOLVED AT"
    ));

    if let Some(tbody) = document.select(&tbody_selector).next() {
        for row in tbody.select(&tr_selector) {
            let data: Vec<_> = row.select(&td_selector).collect();
            if data.len() >= 3 {
                let challenge = data[0]
                    .select(&a_selector)
                    .next()
                    .map_or("N/A".to_string(), |n| n.text().collect::<String>());
                let solves = data[1]
                    .select(&p_selector)
                    .next()
                    .map_or("N/A".to_string(), |n| extract_text_excluding_style(&n));
                let solve_at = data[2]
                    .select(&p_selector)
                    .next()
                    .map_or("N/A".to_string(), |n| extract_text_excluding_style(&n));
                result.push(format!("{:20}{:20}{:20}", challenge, solves, solve_at));
            }
        }
    } else {
        result.push(format!("No data found for user: {}", user));
    }

    Ok(result.join("\n"))
}

pub fn create_alpacahack_user_table_if_not_exists() -> Result<()> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alpacahack_users (name TEXT NOT NULL UNIQUE)",
        [],
    )?;
    Ok(())
}

pub fn insert_alpacahack_user(name: &str) -> Result<String> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute("INSERT INTO alpacahack_users (name) VALUES (?1)", [name])?;
    Ok(format!("Added user: {}", name))
}

pub fn delete_alpacahack_user(name: &str) -> Result<String> {
    let conn = Connection::open("alpacahack.db")?;
    conn.execute("DELETE FROM alpacahack_users WHERE name = ?1", [name])?;
    Ok(format!("Deleted user: {}", name))
}

pub fn get_all_alpacahack_users() -> Result<Vec<String>> {
    let conn = Connection::open("alpacahack.db")?;
    let mut stmt = conn.prepare("SELECT name FROM alpacahack_users")?;
    let mut rows = stmt.query([])?;
    let mut users = Vec::new();
    while let Some(row) = rows.next()? {
        users.push(row.get(0)?);
    }
    Ok(users)
}
